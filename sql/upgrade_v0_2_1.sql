-- Fix correlated Storage object name resolution on existing installs.
begin;
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
