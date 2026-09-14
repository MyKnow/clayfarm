-- Run AFTER 00_fixture.sql and sql/bootstrap.sql, on an empty throwaway PostgreSQL 16 database.
\set ON_ERROR_STOP on
insert into auth.users(id) values
 ('10000000-0000-0000-0000-000000000001'), -- caller, farm 1
 ('10000000-0000-0000-0000-000000000002'), -- worker A
 ('10000000-0000-0000-0000-000000000003'), -- worker B
 ('10000000-0000-0000-0000-000000000004'); -- foreign caller, farm 2
insert into public.cf_members(user_id,farm_id,role,name) values
 ('10000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','caller','caller'),
 ('10000000-0000-0000-0000-000000000002','20000000-0000-0000-0000-000000000001','worker','worker-a'),
 ('10000000-0000-0000-0000-000000000003','20000000-0000-0000-0000-000000000001','worker','worker-b'),
 ('10000000-0000-0000-0000-000000000004','20000000-0000-0000-0000-000000000002','caller','foreign');
insert into storage.objects(bucket_id,name) values('clayfarm','20000000-0000-0000-0000-000000000001/10000000-0000-0000-0000-000000000001/input.png');
set role authenticated;
select set_config('request.jwt.claim.sub','10000000-0000-0000-0000-000000000001',false);
select public.cf_test_assert(not has_table_privilege(current_user,'public.cf_tasks','UPDATE'),'no direct task updates');
select public.cf_test_assert(not has_function_privilege('anon','public.cf_rpc(text,jsonb)','EXECUTE'),'anonymous RPC denied');
select public.cf_test_assert(public.cf_rpc('me','{}')->>'role'='caller','caller membership');
select public.cf_rpc('submit', jsonb_build_object(
 'id','30000000-0000-0000-0000-000000000001','request_hash',repeat('a',64),'spec',jsonb_build_object('name','test'),
 'caller',jsonb_build_object('agent','test'), 'tasks',jsonb_build_array(
   jsonb_build_object('id','40000000-0000-0000-0000-000000000001','job_id','30000000-0000-0000-0000-000000000001','kind','reconstruct','capability','sf3d','slot','gpu','priority',80,'payload',jsonb_build_object('input',jsonb_build_object('path','20000000-0000-0000-0000-000000000001/10000000-0000-0000-0000-000000000001/input.png'))),
   jsonb_build_object('id','40000000-0000-0000-0000-000000000002','job_id','30000000-0000-0000-0000-000000000001','parent_id','40000000-0000-0000-0000-000000000001','kind','process','capability','blender','slot','cpu','priority',90,'payload','{}'::jsonb),
   jsonb_build_object('id','40000000-0000-0000-0000-000000000003','job_id','30000000-0000-0000-0000-000000000001','kind','reconstruct','capability','triposr','slot','gpu','priority',80,'payload','{}'::jsonb)
  ))) as submission;
select public.cf_test_assert((select count(*) from public.cf_tasks)=3,'same-farm task reads');
select public.cf_test_assert((public.cf_rpc('submit',jsonb_build_object('id','30000000-0000-0000-0000-000000000001','request_hash',repeat('a',64)))->>'existing')::boolean,'idempotent submit');
select set_config('request.jwt.claim.sub','10000000-0000-0000-0000-000000000004',false);
select public.cf_test_assert((select count(*) from public.cf_tasks)=0,'foreign-farm task RLS');
select public.cf_test_assert((select count(*) from public.cf_jobs)=0,'foreign-farm job RLS');
select public.cf_test_assert((select count(*) from storage.objects)=0,'foreign-farm storage RLS');
do $$begin
  perform public.cf_rpc('get','{"id":"30000000-0000-0000-0000-000000000001"}');
  raise exception 'TEST FAILED: foreign get accepted';
exception when raise_exception then
  if sqlerrm<>'job_not_found' then raise; end if;
end $$;
select set_config('request.jwt.claim.sub','10000000-0000-0000-0000-000000000002',false);
select public.cf_rpc('heartbeat','{"capabilities":["sf3d","triposr","blender"]}');
select public.cf_test_assert(public.cf_rpc('claim','{"slot":"cpu"}')='null'::jsonb,'parent output required');
select public.cf_rpc('claim','{"slot":"gpu","task_id":"40000000-0000-0000-0000-000000000001"}')->>'attempt_id' as first_attempt \gset
select public.cf_test_assert(public.cf_rpc('claim','{"slot":"gpu"}')='null'::jsonb,'one computing task per GPU slot');
select public.cf_test_assert((public.cf_rpc('computed',jsonb_build_object('task_id','40000000-0000-0000-0000-000000000001','attempt_id',:'first_attempt'))->>'accepted')::boolean,'computed stage accepted');
select public.cf_rpc('claim','{"slot":"gpu"}')->>'id' as second_task \gset
select public.cf_test_assert(:'second_task'='40000000-0000-0000-0000-000000000003','compute slot freed before upload');
-- Force a lost worker / expired lease in this test fixture only.
reset role;
update public.cf_tasks set lease_until=clock_timestamp()-interval '1 second' where id='40000000-0000-0000-0000-000000000001';
set role authenticated;
select set_config('request.jwt.claim.sub','10000000-0000-0000-0000-000000000003',false);
select public.cf_rpc('heartbeat','{"capabilities":["sf3d","blender"]}');
select public.cf_rpc('claim','{"slot":"gpu"}')->>'attempt_id' as replacement_attempt \gset
select public.cf_test_assert(:'replacement_attempt'<>:'first_attempt','replacement fence differs');
select set_config('request.jwt.claim.sub','10000000-0000-0000-0000-000000000002',false);
select public.cf_test_assert(not (public.cf_rpc('finish',jsonb_build_object('task_id','40000000-0000-0000-0000-000000000001','attempt_id',:'first_attempt','output','{}'::jsonb))->>'accepted')::boolean,'late old result rejected');
select set_config('request.jwt.claim.sub','10000000-0000-0000-0000-000000000003',false);
select '20000000-0000-0000-0000-000000000001/10000000-0000-0000-0000-000000000003/40000000-0000-0000-0000-000000000001/'||:'replacement_attempt'||'/mesh.glb' as object_key \gset
-- This tests metadata/RLS, not the real Storage API or binary transfer.
insert into storage.objects(bucket_id,name) values('clayfarm',:'object_key');
select public.cf_test_assert((public.cf_rpc('finish',jsonb_build_object('task_id','40000000-0000-0000-0000-000000000001','attempt_id',:'replacement_attempt','output',jsonb_build_object('files',jsonb_build_array(jsonb_build_object('path',:'object_key','sha256',repeat('b',64))))))->>'accepted')::boolean,'current result commit');
select public.cf_test_assert((public.cf_rpc('finish',jsonb_build_object('task_id','40000000-0000-0000-0000-000000000001','attempt_id',:'replacement_attempt'))->>'already_committed')::boolean,'idempotent finish');
select public.cf_test_assert(public.cf_rpc('claim','{"slot":"cpu"}')->>'id'='40000000-0000-0000-0000-000000000002','dependency unlocked after commit');
-- Worker approval is denied even when membership is active.
do $$begin
  perform public.cf_rpc('approve','{"id":"30000000-0000-0000-0000-000000000001","task_id":"40000000-0000-0000-0000-000000000002"}');
  raise exception 'TEST FAILED: worker approved';
exception when insufficient_privilege then null;
end $$;
reset role;
update public.cf_members set active=false where user_id='10000000-0000-0000-0000-000000000003';
set role authenticated;
do $$begin
  perform public.cf_rpc('me','{}');
  raise exception 'TEST FAILED: revoked member accepted';
exception when insufficient_privilege then null;
end $$;
reset role;
select 'PostgreSQL stub smoke tests passed (does not validate hosted Auth/TUS)' as result;
