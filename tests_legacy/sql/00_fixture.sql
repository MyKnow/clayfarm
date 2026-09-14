-- TEST DATABASE ONLY. These are small Auth/Storage stubs, NOT a Supabase installation.
-- Never run this fixture in a real Supabase project.
\set ON_ERROR_STOP on
create role anon nologin;
create role authenticated nologin;
create role service_role nologin bypassrls;
create schema auth;
create table auth.users(id uuid primary key);
create function auth.uid() returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid
$$;
grant usage on schema auth to authenticated,anon,service_role;
grant execute on function auth.uid() to authenticated,anon,service_role;
create schema storage;
create table storage.objects(id bigint generated always as identity primary key,bucket_id text not null,name text not null,unique(bucket_id,name));
create function storage.foldername(name text) returns text[] language sql immutable as $$
  select (string_to_array(name,'/'))[1:array_length(string_to_array(name,'/'),1)-1]
$$;
alter table storage.objects enable row level security;
grant usage on schema storage to authenticated,service_role;
grant select,insert on storage.objects to authenticated;
grant usage,select on all sequences in schema storage to authenticated;
grant execute on function storage.foldername(text) to authenticated;
create function public.cf_test_assert(value boolean,message text) returns void language plpgsql as $$
begin
  if value is distinct from true then raise exception 'TEST FAILED: %',message; end if;
end $$;
