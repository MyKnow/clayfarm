-- ClayFarm v0.1.0. Run ONCE in a NEW / DEDICATED Supabase project's SQL editor.
-- No SQL editor secrets. No service_role credential is distributed to workers.
-- This is a bootstrap script, not an automatically applied migration.
begin;
create schema if not exists clayfarm_private;
revoke all on schema clayfarm_private from public, anon;
grant usage on schema clayfarm_private to authenticated;

create table if not exists public.cf_members (
  user_id uuid primary key references auth.users(id) on delete cascade,
  farm_id uuid not null,
  role text not null check (role in ('caller','worker')),
  name text not null check (length(name) between 1 and 80),
  active boolean not null default true
);
create table if not exists public.cf_jobs (
  id uuid primary key,
  farm_id uuid not null,
  created_by uuid not null references auth.users(id),
  caller jsonb not null default '{}',
  spec jsonb not null,
  request_hash text not null,
  parent_job uuid references public.cf_jobs(id),
  status text not null default 'open' check (status in ('open','approved','cancelled')),
  approved_task uuid,
  created_at timestamptz not null default now()
);
create table if not exists public.cf_tasks (
  id uuid primary key,
  job_id uuid not null references public.cf_jobs(id),
  parent_id uuid references public.cf_tasks(id),
  kind text not null check (kind in ('reconstruct','process','preview')),
  capability text not null check (capability in ('sf3d','triposr','blender','mock')),
  slot text not null check (slot in ('cpu','gpu')),
  payload jsonb not null,
  priority integer not null default 50 check (priority between 0 and 100),
  status text not null default 'queued' check (status in ('queued','running','done','failed','cancelled')),
  compute_done boolean not null default false,
  attempt_no integer not null default 0,
  max_attempts integer not null default 3 check (max_attempts between 1 and 5),
  attempt_id uuid,
  lease_owner uuid references auth.users(id),
  lease_until timestamptz,
  not_before timestamptz not null default now(),
  output jsonb,
  error jsonb,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);
create table if not exists public.cf_workers (
  user_id uuid primary key references auth.users(id) on delete cascade,
  farm_id uuid not null,
  capabilities text[] not null default '{}',
  telemetry jsonb not null default '{}',
  last_seen timestamptz not null default now()
);
create table if not exists public.cf_attempts (
  id uuid primary key,
  task_id uuid not null references public.cf_tasks(id),
  worker_id uuid not null references auth.users(id),
  state text not null default 'running' check (state in ('running','done','failed','expired')),
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  error jsonb
);
create index if not exists cf_tasks_queue on public.cf_tasks(status,slot,priority desc,created_at);
create index if not exists cf_tasks_job on public.cf_tasks(job_id);
create index if not exists cf_tasks_parent on public.cf_tasks(parent_id);
create index if not exists cf_jobs_farm on public.cf_jobs(farm_id);

alter table public.cf_members enable row level security;
alter table public.cf_jobs enable row level security;
alter table public.cf_tasks enable row level security;
alter table public.cf_workers enable row level security;
alter table public.cf_attempts enable row level security;
revoke all on public.cf_members,public.cf_jobs,public.cf_tasks,public.cf_workers,public.cf_attempts from public,anon,authenticated;
grant select on public.cf_members,public.cf_jobs,public.cf_tasks,public.cf_workers,public.cf_attempts to authenticated;
grant all on public.cf_members,public.cf_jobs,public.cf_tasks,public.cf_workers,public.cf_attempts to service_role;

drop policy if exists cf_self on public.cf_members;
create policy cf_self on public.cf_members for select to authenticated using (user_id=(select auth.uid()) and active);
drop policy if exists cf_job_read on public.cf_jobs;
create policy cf_job_read on public.cf_jobs for select to authenticated using
 (exists(select 1 from public.cf_members m where m.user_id=(select auth.uid()) and m.active and m.farm_id=cf_jobs.farm_id));
drop policy if exists cf_task_read on public.cf_tasks;
create policy cf_task_read on public.cf_tasks for select to authenticated using
 (exists(select 1 from public.cf_jobs j where j.id=cf_tasks.job_id));
drop policy if exists cf_worker_read on public.cf_workers;
create policy cf_worker_read on public.cf_workers for select to authenticated using
 (exists(select 1 from public.cf_members m where m.user_id=(select auth.uid()) and m.active and m.farm_id=cf_workers.farm_id));
drop policy if exists cf_attempt_read on public.cf_attempts;
create policy cf_attempt_read on public.cf_attempts for select to authenticated using
 (exists(select 1 from public.cf_tasks t where t.id=cf_attempts.task_id));

-- All elevated writes live in a NON-exposed schema and verify auth.uid + membership.
create or replace function clayfarm_private.dispatch(p_action text,p_args jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare
  m public.cf_members%rowtype;
  t public.cf_tasks%rowtype;
  j public.cf_jobs%rowtype;
  x jsonb;
  f jsonb;
  tid uuid;
  jid uuid;
  token uuid;
  caps text[];
  requested_slot text;
  seconds integer;
  prefix text;
  rows_json jsonb;
begin
  if auth.uid() is null then raise exception 'authentication_required' using errcode='42501'; end if;
  select * into m from public.cf_members where user_id=auth.uid() and active;
  if not found then raise exception 'member_revoked_or_missing' using errcode='42501'; end if;
  if p_args is null or jsonb_typeof(p_args)<>'object' or octet_length(p_args::text)>262144 then
    raise exception 'invalid_arguments';
  end if;
  if p_action='me' then return to_jsonb(m); end if;
  if p_action='workers' then
    select coalesce(jsonb_agg(to_jsonb(w)),'[]'::jsonb) into rows_json from public.cf_workers w where w.farm_id=m.farm_id;
    return rows_json;
  end if;

  if p_action='submit' then
    if m.role<>'caller' then raise exception 'caller_only' using errcode='42501'; end if;
    jid := (p_args->>'id')::uuid;
    select * into j from public.cf_jobs where id=jid;
    if found then
      if j.farm_id<>m.farm_id or j.created_by<>m.user_id or j.request_hash<>p_args->>'request_hash' then
        raise exception 'idempotency_conflict';
      end if;
      return jsonb_build_object('id',jid,'existing',true);
    end if;
    if jsonb_typeof(p_args->'tasks')<>'array' or jsonb_array_length(p_args->'tasks') not between 1 and 32 or
       jsonb_typeof(p_args->'spec')<>'object' or coalesce(p_args->>'request_hash','') !~ '^[0-9a-f]{64}$' then
       raise exception 'invalid_plan';
    end if;
    if p_args->>'parent_job' is not null and not exists(select 1 from public.cf_jobs where id=(p_args->>'parent_job')::uuid and farm_id=m.farm_id) then
       raise exception 'invalid_parent';
    end if;
    insert into public.cf_jobs(id,farm_id,created_by,caller,spec,request_hash,parent_job)
      values(jid,m.farm_id,m.user_id,coalesce(p_args->'caller','{}'),p_args->'spec',p_args->>'request_hash',(p_args->>'parent_job')::uuid);
    for x in select value from jsonb_array_elements(p_args->'tasks') loop
      if (x->>'job_id')::uuid<>jid or jsonb_typeof(x->'payload')<>'object' then raise exception 'invalid_task'; end if;
      if x->>'parent_id' is not null and not exists(select 1 from public.cf_tasks where id=(x->>'parent_id')::uuid and job_id=jid) then
        raise exception 'parent_must_precede_child_in_same_job';
      end if;
      if (x->>'kind'='reconstruct' and (x->>'slot'<>'gpu' or x->>'capability' not in ('sf3d','triposr','mock'))) or
         (x->>'kind' in ('process','preview') and (x->>'slot'<>'cpu' or x->>'capability' not in ('blender','mock'))) then
        raise exception 'invalid_task_capability';
      end if;
      if x->'payload'->'input' is not null then
        if left(coalesce(x->'payload'->'input'->>'path',''),length(m.farm_id::text)+1)<>m.farm_id::text||'/' then
          raise exception 'cross_farm_input';
        end if;
        if not exists(select 1 from storage.objects where bucket_id='clayfarm' and name=x->'payload'->'input'->>'path') then
          raise exception 'upload_input_before_submit';
        end if;
      end if;
      insert into public.cf_tasks(id,job_id,parent_id,kind,capability,slot,payload,priority)
      values((x->>'id')::uuid,jid,(x->>'parent_id')::uuid,x->>'kind',x->>'capability',x->>'slot',x->'payload',coalesce((x->>'priority')::integer,50));
    end loop;
    return jsonb_build_object('id',jid,'existing',false);
  end if;

  if p_action in ('get','cancel','approve') then
    jid := (p_args->>'id')::uuid;
    select * into j from public.cf_jobs where id=jid and farm_id=m.farm_id for update;
    if not found then raise exception 'job_not_found'; end if;
    if p_action in ('cancel','approve') and (m.role<>'caller' or j.created_by<>m.user_id) then
      raise exception 'originating_caller_only' using errcode='42501';
    end if;
    if p_action='cancel' then
      update public.cf_jobs set status='cancelled' where id=jid;
      update public.cf_tasks set status='cancelled',lease_until=null where job_id=jid and status in ('queued','running');
      return jsonb_build_object('cancelled',true);
    elsif p_action='approve' then
      if j.status<>'open' then raise exception 'job_not_open'; end if;
      tid := (p_args->>'task_id')::uuid;
      select * into t from public.cf_tasks where id=tid and job_id=jid and kind='process' and status='done';
      if not found then raise exception 'completed_process_task_required'; end if;
      if coalesce((t.output->>'mock')::boolean,false) then raise exception 'mock_assets_cannot_be_approved'; end if;
      if coalesce((t.output->'metrics'->>'hard_pass')::boolean,false)=false then raise exception 'mechanical_checks_failed'; end if;
      if exists(select 1 from public.cf_tasks where parent_id=tid and status<>'done') then raise exception 'preview_incomplete'; end if;
      update public.cf_jobs set status='approved',approved_task=tid where id=jid;
      update public.cf_tasks set status='cancelled',lease_until=null where job_id=jid and status in ('queued','running');
      return jsonb_build_object('approved',true,'task_id',tid);
    end if;
    select coalesce(jsonb_agg(to_jsonb(q) order by q.created_at,q.id),'[]'::jsonb) into rows_json from public.cf_tasks q where q.job_id=jid;
    return jsonb_build_object('job',to_jsonb(j),'tasks',rows_json);
  end if;

  if m.role<>'worker' then raise exception 'worker_only' using errcode='42501'; end if;
  if p_action='heartbeat' then
    select coalesce(array_agg(value),'{}'::text[]) into caps from jsonb_array_elements_text(coalesce(p_args->'capabilities','[]'));
    if not caps <@ array['sf3d','triposr','blender','mock'] then raise exception 'invalid_capabilities'; end if;
    insert into public.cf_workers(user_id,farm_id,capabilities,telemetry,last_seen)
      values(m.user_id,m.farm_id,caps,coalesce(p_args->'telemetry','{}'),clock_timestamp())
      on conflict(user_id) do update set capabilities=excluded.capabilities,telemetry=excluded.telemetry,last_seen=excluded.last_seen;
    return jsonb_build_object('ok',true);
  end if;

  if p_action in ('claim','peek') then
    requested_slot := p_args->>'slot';
    if requested_slot not in ('cpu','gpu') then raise exception 'invalid_slot'; end if;
    select capabilities into caps from public.cf_workers where user_id=m.user_id;
    if caps is null then return 'null'::jsonb; end if;
    -- Cleanup is opportunistic; no scheduler daemon / cron is required.
    update public.cf_attempts a set state='expired',ended_at=clock_timestamp()
    from public.cf_tasks q join public.cf_jobs qj on qj.id=q.job_id
    where a.id=q.attempt_id and a.state='running' and q.status='running' and q.lease_until<clock_timestamp() and qj.farm_id=m.farm_id;
    update public.cf_tasks q set status='failed',error='{"code":"attempts_exhausted"}'::jsonb
    from public.cf_jobs qj where qj.id=q.job_id and qj.farm_id=m.farm_id and q.status='running'
      and q.lease_until<clock_timestamp() and q.attempt_no>=q.max_attempts;
    with recursive bad(id) as (
      select q.id from public.cf_tasks q join public.cf_jobs qj on qj.id=q.job_id
        where qj.farm_id=m.farm_id and q.status in ('failed','cancelled')
      union all
      select c.id from public.cf_tasks c join bad b on c.parent_id=b.id where c.status in ('queued','running')
    ) update public.cf_tasks q set status='failed',error='{"code":"dependency_failed"}'::jsonb
      where q.id in (select id from bad) and q.status in ('queued','running');

    if p_action='peek' then
      select coalesce(jsonb_agg(v.item),'[]'::jsonb) into rows_json from (
        select to_jsonb(q)||jsonb_build_object('parent_output',p.output) as item
        from public.cf_tasks q join public.cf_jobs qj on qj.id=q.job_id left join public.cf_tasks p on p.id=q.parent_id
        where qj.farm_id=m.farm_id and qj.status='open' and q.status='queued' and q.slot=requested_slot
          and q.capability=any(caps) and (q.parent_id is null or p.status='done') and q.not_before<=clock_timestamp()
        order by q.priority desc,q.created_at,q.id limit 2
      ) v;
      return rows_json;
    end if;
    -- A node can lease at most one task per CPU/GPU slot. Locks on its worker row
    -- serialize competing claims from accidentally started duplicate daemons.
    perform 1 from public.cf_workers where user_id=m.user_id for update;
    if exists(select 1 from public.cf_tasks where lease_owner=m.user_id and slot=requested_slot and status='running' and not compute_done and lease_until>clock_timestamp()) then
      return 'null'::jsonb;
    end if;
    select q.* into t from public.cf_tasks q join public.cf_jobs qj on qj.id=q.job_id left join public.cf_tasks p on p.id=q.parent_id
    where qj.farm_id=m.farm_id and qj.status='open' and q.slot=requested_slot and q.capability=any(caps)
      and (q.status='queued' or (q.status='running' and q.lease_until<clock_timestamp()))
      and q.attempt_no<q.max_attempts and q.not_before<=clock_timestamp()
      and (q.parent_id is null or p.status='done')
      and (p_args->>'task_id' is null or q.id=(p_args->>'task_id')::uuid)
    order by q.priority desc,(p.lease_owner=m.user_id) desc nulls last,q.created_at,q.id
    for update of q skip locked limit 1;
    if not found then return 'null'::jsonb; end if;
    seconds := greatest(15,least(600,coalesce((p_args->>'seconds')::integer,120)));
    token := gen_random_uuid();
    update public.cf_tasks set status='running',compute_done=false,lease_owner=m.user_id,attempt_id=token,attempt_no=attempt_no+1,
      lease_until=clock_timestamp()+make_interval(secs=>seconds) where id=t.id returning * into t;
    insert into public.cf_attempts(id,task_id,worker_id) values(token,t.id,m.user_id);
    return to_jsonb(t)||jsonb_build_object('parent_output',(select output from public.cf_tasks where id=t.parent_id));
  end if;

  if p_action in ('renew','computed','finish','fail') then
    tid := (p_args->>'task_id')::uuid; token := (p_args->>'attempt_id')::uuid;
    select q.* into t from public.cf_tasks q join public.cf_jobs qj on qj.id=q.job_id
      where q.id=tid and qj.farm_id=m.farm_id for update of q;
    if not found then raise exception 'task_not_found'; end if;
    if p_action='finish' and t.status='done' and t.lease_owner=m.user_id and t.attempt_id=token then
      return jsonb_build_object('accepted',true,'already_committed',true);
    end if;
    if t.status<>'running' or t.lease_owner is distinct from m.user_id or t.attempt_id is distinct from token or
       t.lease_until is null or t.lease_until<=clock_timestamp() or not exists(select 1 from public.cf_jobs where id=t.job_id and status='open') then
      return jsonb_build_object('accepted',false,'reason','lease_lost');
    end if;
    if p_action='computed' then
      update public.cf_tasks set compute_done=true where id=tid;
      return jsonb_build_object('accepted',true);
    elsif p_action='renew' then
      seconds := greatest(15,least(600,coalesce((p_args->>'seconds')::integer,120)));
      update public.cf_tasks set lease_until=clock_timestamp()+make_interval(secs=>seconds) where id=tid;
      return jsonb_build_object('accepted',true);
    elsif p_action='fail' then
      update public.cf_attempts set state='failed',ended_at=clock_timestamp(),error=p_args->'error' where id=token;
      update public.cf_tasks set status=case when attempt_no>=max_attempts then 'failed' else 'queued' end,
        lease_until=null,error=p_args->'error',not_before=clock_timestamp()+make_interval(secs=>least(60,attempt_no*5)) where id=tid;
      return jsonb_build_object('accepted',true);
    end if;
    x := p_args->'output';
    if jsonb_typeof(x)<>'object' or octet_length(x::text)>32768 or jsonb_typeof(x->'files')<>'array' or jsonb_array_length(x->'files') not between 1 and 16 then raise exception 'invalid_output'; end if;
    prefix := m.farm_id::text||'/'||m.user_id::text||'/'||tid::text||'/'||token::text||'/';
    for f in select value from jsonb_array_elements(x->'files') loop
      if left(coalesce(f->>'path',''),length(prefix))<>prefix or coalesce(f->>'sha256','') !~ '^[0-9a-f]{64}$' then raise exception 'invalid_artifact_scope'; end if;
      if not exists(select 1 from storage.objects where bucket_id='clayfarm' and name=f->>'path') then raise exception 'upload_before_commit'; end if;
    end loop;
    update public.cf_tasks set status='done',output=x,completed_at=clock_timestamp(),lease_until=null where id=tid;
    update public.cf_attempts set state='done',ended_at=clock_timestamp() where id=token;
    return jsonb_build_object('accepted',true);
  end if;
  raise exception 'unknown_action';
end;
$$;
revoke all on function clayfarm_private.dispatch(text,jsonb) from public,anon,authenticated;
grant execute on function clayfarm_private.dispatch(text,jsonb) to authenticated;

create or replace function public.cf_rpc(p_action text,p_args jsonb default '{}')
returns jsonb language sql security invoker set search_path='' as $$
  select clayfarm_private.dispatch(p_action,p_args);
$$;
revoke all on function public.cf_rpc(text,jsonb) from public,anon;
grant execute on function public.cf_rpc(text,jsonb) to authenticated;

-- Create the private 'clayfarm' bucket using the CLI admin-init API, NOT a SQL INSERT.
-- Upload keys: farm UUID / auth user UUID / ... . No overwrites, no worker deletes.
drop policy if exists cf_storage_read on storage.objects;
create policy cf_storage_read on storage.objects for select to authenticated using (
  bucket_id='clayfarm' and exists(select 1 from public.cf_members m where m.user_id=(select auth.uid())
    and m.active and (storage.foldername(storage.objects.name))[1]=m.farm_id::text)
);
drop policy if exists cf_storage_insert on storage.objects;
create policy cf_storage_insert on storage.objects for insert to authenticated with check (
  bucket_id='clayfarm' and (storage.foldername(storage.objects.name))[2]=(select auth.uid())::text
  and exists(select 1 from public.cf_members m where m.user_id=(select auth.uid())
    and m.active and (storage.foldername(storage.objects.name))[1]=m.farm_id::text)
);
notify pgrst,'reload schema';
commit;
