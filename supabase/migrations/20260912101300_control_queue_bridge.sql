-- Requires the existing ClayFarm bootstrap and initialized cf_control tables.
-- Operator applies to a backed-up database. Never creates a farm or Auth account.
begin;
-- Fail before any mutation if the operational dispatcher changed since import.
-- The accepted body hash was independently read from the existing server.
do $$ begin
  if (select md5(prosrc) from pg_proc where oid=to_regprocedure('clayfarm_private.dispatch(text,jsonb)'))
     is distinct from '5f236654413ae934971d9a6e27c45a61' then
    raise exception 'queue_source_changed: inspect and merge the newer dispatcher before migration';
  end if;
end $$;
create table clayfarm_private.worker_identities (
  id uuid primary key,
  auth_user uuid unique references auth.users(id) on delete cascade,
  node_id text unique references cf_control.nodes(id) on delete cascade,
  check ((auth_user is not null)::int + (node_id is not null)::int = 1),
  check (id = coalesce(auth_user,node_id::uuid))
);
insert into clayfarm_private.worker_identities(id,auth_user) select id,id from auth.users;
alter table public.cf_workers drop constraint cf_workers_user_id_fkey,
  add constraint cf_workers_user_id_fkey foreign key(user_id) references clayfarm_private.worker_identities(id) on delete cascade;
alter table public.cf_tasks drop constraint cf_tasks_lease_owner_fkey,
  add constraint cf_tasks_lease_owner_fkey foreign key(lease_owner) references clayfarm_private.worker_identities(id);
alter table public.cf_attempts drop constraint cf_attempts_worker_id_fkey,
  add constraint cf_attempts_worker_id_fkey foreign key(worker_id) references clayfarm_private.worker_identities(id);

create function clayfarm_private.track_legacy_identity() returns trigger language plpgsql
security definer set search_path='' as $$
begin
  insert into clayfarm_private.worker_identities(id,auth_user) values(new.user_id,new.user_id)
    on conflict(auth_user) do nothing;
  return new;
end $$;
revoke all on function clayfarm_private.track_legacy_identity() from public,anon,authenticated;
create trigger cf_track_identity after insert on public.cf_members
  for each row execute function clayfarm_private.track_legacy_identity();

create table cf_control.farm_binding (
  singleton boolean primary key default true check(singleton),
  farm_id uuid not null
);
create table cf_control.bridge_artifacts (
  path text primary key, actor text not null, sha256 text not null, size bigint not null
);
revoke all on cf_control.bridge_artifacts from public,anon,authenticated;
create table cf_control.node_engines (
  node_id text primary key references cf_control.nodes(id),
  engines text[] not null default '{}',
  check(engines <@ array['sf3d','triposr','blender'])
);
revoke all on clayfarm_private.worker_identities,cf_control.farm_binding,cf_control.node_engines from public,anon,authenticated;

-- Locked current authorization; caller-supplied identity is usable only by the
-- non-public server role. No JWT, password or Auth identity is created for nodes.
create function clayfarm_private.control_member(p_actor uuid,p_kind text,p_session text default null)
returns public.cf_members language plpgsql security definer set search_path='' as $$
declare
  u cf_control.users%rowtype; n cf_control.nodes%rowtype; m public.cf_members%rowtype;
begin
  select farm_id into m.farm_id from cf_control.farm_binding where singleton;
  if m.farm_id is null then raise exception 'farm_not_bound' using errcode='55000'; end if;
  if p_kind='node' then
    select * into n from cf_control.nodes where id=p_actor::text for share;
    if not found or n.status<>'active' then raise exception 'node_not_active' using errcode='42501'; end if;
    select * into u from cf_control.users where id=n.owner for share;
    if not found or u.status<>'active' then raise exception 'owner_suspended' using errcode='42501'; end if;
    insert into clayfarm_private.worker_identities(id,node_id) values(p_actor,n.id)
      on conflict(node_id) do nothing;
    m.role:='worker'; m.name:=left(n.name,80);
  elsif p_kind='human' then
    select * into u from cf_control.users where id=p_actor::text for share;
    if not found or u.status<>'active' or not (u.grants::jsonb ? 'creator-basic') then
      raise exception 'approval_required' using errcode='42501';
    end if;
    if p_session is not null and exists(select 1 from cf_control.revocations where session_id=p_session) then
      raise exception 'session_revoked' using errcode='42501';
    end if;
    if not exists(select 1 from auth.users where id=p_actor) then
      raise exception 'auth_identity_missing' using errcode='42501';
    end if;
    m.role:='caller'; m.name:=left(u.email,80);
  else raise exception 'invalid_identity_kind' using errcode='42501';
  end if;
  m.user_id:=p_actor; m.active:=true;
  return m;
end $$;
revoke all on function clayfarm_private.control_member(uuid,text,text) from public,anon,authenticated;

create or replace function clayfarm_private.queue_dispatch(m public.cf_members,p_action text,p_args jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare
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

revoke all on function clayfarm_private.queue_dispatch(public.cf_members,text,jsonb) from public,anon,authenticated;

-- Existing cf_rpc remains compatible and calls the SAME task implementation.
create or replace function clayfarm_private.dispatch(p_action text,p_args jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare m public.cf_members%rowtype;
begin
  if auth.uid() is null then raise exception 'authentication_required' using errcode='42501'; end if;
  select * into m from public.cf_members where user_id=auth.uid() and active;
  if not found then raise exception 'member_revoked_or_missing' using errcode='42501'; end if;
  return clayfarm_private.queue_dispatch(m,p_action,p_args);
end $$;

create function clayfarm_private.control_rpc(p_actor uuid,p_kind text,p_action text,p_args jsonb,p_session text default null)
returns jsonb language plpgsql security definer set search_path='' as $$
declare m public.cf_members%rowtype; job_record public.cf_jobs%rowtype; caps text[]; w public.cf_workers%rowtype;
begin
  m:=clayfarm_private.control_member(p_actor,p_kind,p_session);
  if p_args is null or jsonb_typeof(p_args)<>'object' or octet_length(p_args::text)>262144 then
    raise exception 'invalid_arguments' using errcode='22023';
  end if;
  if p_kind='human' then
    if p_action not in ('me','workers','submit','get','cancel','approve','list') then
      raise exception 'caller_only' using errcode='42501';
    end if;
    if p_action='list' then
      return coalesce((select jsonb_agg(to_jsonb(v)) from
        (select * from public.cf_jobs where farm_id=m.farm_id and created_by=m.user_id order by created_at desc limit 200) v),'[]');
    end if;
    if p_action in ('get','cancel','approve') then
      select * into job_record from public.cf_jobs where id=(p_args->>'id')::uuid;
      if not found or job_record.farm_id<>m.farm_id or job_record.created_by<>m.user_id then raise exception 'job_not_found' using errcode='42501'; end if;
    end if;
    if p_action='approve' and exists(select 1 from public.cf_tasks where job_id=job_record.id and output->>'mock'='true') then
      raise exception 'mock_not_approvable' using errcode='22023';
    end if;
    if p_action='submit' then
      if exists(select 1 from jsonb_array_elements(p_args->'tasks') q where q->>'capability'='mock') then
        raise exception 'mock_not_allowed' using errcode='22023';
      end if;
      -- Every direct input belongs to this caller's staged input or one of their
      -- completed tasks; an arbitrary same-farm path is not enough.
      if exists(select 1 from jsonb_array_elements(p_args->'tasks') q
        where q->'payload'->'input' is not null and not clayfarm_private.control_readable(m,p_kind,q->'payload'->'input'->>'path')) then
        raise exception 'input_scope_denied' using errcode='42501';
      end if;
      if exists(select 1 from jsonb_array_elements(p_args->'tasks') q,
        public.cf_tasks source_task,jsonb_array_elements(source_task.output->'files') f
        where q->'payload'->'input'->>'path'=f->>'path' and source_task.output->>'mock'='true') then
        raise exception 'mock_revision_not_allowed' using errcode='22023';
      end if;
      if p_args->>'parent_job' is not null and not exists(select 1 from public.cf_jobs
        where id=(p_args->>'parent_job')::uuid and created_by=m.user_id and farm_id=m.farm_id) then
        raise exception 'invalid_parent' using errcode='42501';
      end if;
    end if;
  else
    if p_action not in ('me','get','heartbeat','peek','claim','renew','computed','finish','fail') then
      raise exception 'worker_only' using errcode='42501';
    end if;
    if p_action='peek' then return '[]'::jsonb; end if;
    if p_action='get' and not exists(select 1 from public.cf_tasks t join public.cf_jobs j on j.id=t.job_id
      where t.job_id=(p_args->>'id')::uuid and j.farm_id=m.farm_id and t.lease_owner=m.user_id) then
      raise exception 'job_not_found' using errcode='42501';
    end if;
    if p_action='heartbeat' then
      select coalesce(array_agg(v),'{}') into caps from jsonb_array_elements_text(coalesce(p_args->'capabilities','[]')) v
        where v=any(coalesce((select engines from cf_control.node_engines where node_id=p_actor::text),'{}'));
      p_args:=jsonb_set(p_args,'{capabilities}',to_jsonb(caps));
    end if;
    if p_action='claim' then
      select * into w from public.cf_workers where user_id=m.user_id for update;
      if not found or w.last_seen < clock_timestamp()-interval '90 seconds' then
        raise exception 'heartbeat_required' using errcode='55000';
      end if;
      -- Re-evaluate administrative engine removal even before the next heartbeat.
      select coalesce(engines,'{}') into caps from cf_control.node_engines where node_id=p_actor::text;
      update public.cf_workers set capabilities=array(select unnest(w.capabilities) intersect select unnest(coalesce(caps,'{}'))) where user_id=m.user_id;
      if coalesce((w.telemetry->>'paused')::boolean,false) or
        (coalesce((w.telemetry->>'on_battery')::boolean,false) and not coalesce((w.telemetry->>'allow_battery')::boolean,false)) then return 'null'; end if;
      -- Shared/unified memory: one compute task across both slots for new nodes.
      if exists(select 1 from public.cf_tasks where lease_owner=m.user_id and status='running'
        and not compute_done and lease_until>clock_timestamp()) then return 'null'; end if;
    end if;
  end if;
  return clayfarm_private.queue_dispatch(m,p_action,p_args);
end $$;
revoke all on function clayfarm_private.control_rpc(uuid,text,text,jsonb,text) from public,anon,authenticated;

create function clayfarm_private.control_readable(m public.cf_members,p_kind text,p_path text)
returns boolean language sql stable security definer set search_path='' as $$
select split_part(p_path,'/',1)=m.farm_id::text and (
  (p_kind='human' and (
    (split_part(p_path,'/',2)=m.user_id::text and split_part(p_path,'/',4)='inputs') or
    exists(select 1 from public.cf_tasks t join public.cf_jobs j on j.id=t.job_id,
      jsonb_array_elements(t.output->'files') f where j.farm_id=m.farm_id and j.created_by=m.user_id and f->>'path'=p_path and t.status='done')
  )) or
  (p_kind='node' and exists(select 1 from public.cf_tasks t join public.cf_jobs j on j.id=t.job_id
    left join public.cf_tasks p on p.id=t.parent_id
    where j.farm_id=m.farm_id and j.status='open' and t.lease_owner=m.user_id and t.status='running'
      and t.lease_until>clock_timestamp() and (
        t.payload->'input'->>'path'=p_path or exists(select 1 from jsonb_array_elements(p.output->'files') f where f->>'path'=p_path)
      )))
);
$$;
revoke all on function clayfarm_private.control_readable(public.cf_members,text,text) from public,anon,authenticated;

create function clayfarm_private.control_storage(p_actor uuid,p_kind text,p_path text,p_write boolean,p_session text default null)
returns boolean language plpgsql security definer set search_path='' as $$
declare m public.cf_members%rowtype; parts text[]; t public.cf_tasks%rowtype;
begin
  m:=clayfarm_private.control_member(p_actor,p_kind,p_session);
  parts:=string_to_array(p_path,'/');
  if array_length(parts,1)<>5 or parts[1]<>m.farm_id::text or p_path like '%..%' or p_path like E'%\\\\%' or
    parts[5] !~ '^[0-9a-f]{64}-[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$' then
    raise exception 'invalid_artifact_scope' using errcode='42501';
  end if;
  if not p_write then
    if not coalesce(clayfarm_private.control_readable(m,p_kind,p_path),false) then
      raise exception 'artifact_scope_denied' using errcode='42501';
    end if;
    return true;
  end if;
  if parts[2]<>m.user_id::text then raise exception 'artifact_scope_denied' using errcode='42501'; end if;
  if p_kind='human' then
    perform parts[3]::uuid;
    if parts[4]<>'inputs' or exists(select 1 from public.cf_jobs where id=parts[3]::uuid) then
      raise exception 'input_is_immutable' using errcode='42501';
    end if;
  else
    select q.* into t from public.cf_tasks q join public.cf_jobs j on j.id=q.job_id
      where q.id=parts[3]::uuid and j.farm_id=m.farm_id and j.status='open' for share of q;
    if not found or t.lease_owner is distinct from m.user_id or t.attempt_id is distinct from parts[4]::uuid
      or t.status<>'running' or t.lease_until is null or t.lease_until<=clock_timestamp() then
      raise exception 'stale_attempt' using errcode='42501';
    end if;
  end if;
  return true;
end $$;
revoke all on function clayfarm_private.control_storage(uuid,text,text,boolean,text) from public,anon,authenticated;

-- Narrow lookup for idempotent result reconciliation; no direct table grant.
create function clayfarm_private.control_committed(p_actor uuid,p_task uuid,p_attempt uuid)
returns jsonb language plpgsql security definer set search_path='' as $$
declare m public.cf_members%rowtype; result jsonb;
begin
  m:=clayfarm_private.control_member(p_actor,'node',null);
  select t.output into result from public.cf_tasks t join public.cf_jobs j on j.id=t.job_id
    where t.id=p_task and t.attempt_id=p_attempt and t.lease_owner=m.user_id
      and t.status='done' and j.farm_id=m.farm_id;
  return result;
end $$;
revoke all on function clayfarm_private.control_committed(uuid,uuid,uuid) from public,anon,authenticated;

do $$ begin
  if not exists(select 1 from pg_roles where rolname='clayfarm_gateway') then create role clayfarm_gateway nologin; end if;
end $$;
grant usage on schema cf_control,clayfarm_private to clayfarm_gateway;
grant select,insert,update,delete on all tables in schema cf_control to clayfarm_gateway;
revoke insert,update,delete on cf_control.farm_binding from clayfarm_gateway;
grant usage,select on all sequences in schema cf_control to clayfarm_gateway;
grant execute on function clayfarm_private.control_member(uuid,text,text),
  clayfarm_private.control_rpc(uuid,text,text,jsonb,text),
  clayfarm_private.control_storage(uuid,text,text,boolean,text) to clayfarm_gateway;
grant execute on function clayfarm_private.control_committed(uuid,uuid,uuid) to clayfarm_gateway;
notify pgrst,'reload schema';
commit;
