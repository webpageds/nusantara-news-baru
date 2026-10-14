-- NusantaraNews newsroom schema (Supabase SQL Editor)
-- Jalankan seluruh file ini setelah membuat project Supabase.
-- Prinsip: tidak ada signup publik; admin mengundang akun via Supabase Auth.
create extension if not exists pgcrypto;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  full_name text not null default 'Anggota Redaksi',
  role text not null default 'editor' check (role in ('admin','editor')),
  created_at timestamptz not null default now()
);

create table if not exists public.articles (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  slug text not null unique,
  category text not null default 'Nasional',
  excerpt text not null default '',
  body text not null default '',
  image_url text,
  image_caption text,
  image_urls jsonb not null default '[]'::jsonb check (jsonb_typeof(image_urls) = 'array' and jsonb_array_length(image_urls) <= 2),
  image_captions jsonb not null default '[]'::jsonb check (jsonb_typeof(image_captions) = 'array' and jsonb_array_length(image_captions) <= 2),
  author_name text not null default '',
  source_name text,
  source_url text,
  status text not null default 'draft' check (status in ('draft','published')),
  published_at timestamptz,
  created_by uuid not null references auth.users(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists articles_status_published_at_idx on public.articles(status, published_at desc);
create index if not exists articles_created_by_idx on public.articles(created_by);
alter table public.profiles enable row level security;
alter table public.articles enable row level security;

-- Role lookup function avoids recursive profile RLS.
create or replace function public.current_newsroom_role()
returns text language sql stable security definer
set search_path = public
as $$
  select role from public.profiles where id = auth.uid()
$$;
revoke all on function public.current_newsroom_role() from public;
grant execute on function public.current_newsroom_role() to anon, authenticated;

drop policy if exists "Profiles read by newsroom" on public.profiles;
create policy "Profiles read by newsroom" on public.profiles
for select to authenticated
using (public.current_newsroom_role() = 'admin' or id = auth.uid());

drop policy if exists "Admin manages profiles" on public.profiles;
create policy "Admin manages profiles" on public.profiles
for all to authenticated
using (public.current_newsroom_role() = 'admin')
with check (public.current_newsroom_role() = 'admin');

drop policy if exists "Public reads published articles" on public.articles;
create policy "Public reads published articles" on public.articles
for select to anon, authenticated
using (status = 'published' or (auth.uid() is not null and (created_by = auth.uid() or public.current_newsroom_role() = 'admin')));

drop policy if exists "Editors create own drafts" on public.articles;
create policy "Editors create own drafts" on public.articles
for insert to authenticated
with check (created_by = auth.uid() and (status = 'draft' or public.current_newsroom_role() = 'admin'));

drop policy if exists "Editors update own drafts and admin updates all" on public.articles;
create policy "Editors update own drafts and admin updates all" on public.articles
for update to authenticated
using ((created_by = auth.uid() and status = 'draft') or public.current_newsroom_role() = 'admin')
with check (
  (created_by = auth.uid() and status = 'draft')
  or public.current_newsroom_role() = 'admin'
);

drop policy if exists "Admin deletes articles" on public.articles;
create policy "Admin deletes articles" on public.articles
for delete to authenticated
using (public.current_newsroom_role() = 'admin');

-- Public bucket: published article images need public URLs. Upload is restricted to logged-in newsroom users.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('news-media', 'news-media', true, 5242880, array['image/jpeg','image/png','image/webp','image/avif'])
on conflict (id) do update set public = true, file_size_limit = 5242880,
allowed_mime_types = array['image/jpeg','image/png','image/webp','image/avif'];

drop policy if exists "Public reads newsroom images" on storage.objects;
create policy "Public reads newsroom images" on storage.objects
for select to anon, authenticated using (bucket_id = 'news-media');

drop policy if exists "Newsroom uploads own folder" on storage.objects;
create policy "Newsroom uploads own folder" on storage.objects
for insert to authenticated
with check (
  bucket_id = 'news-media'
  and (storage.foldername(name))[1] = auth.uid()::text
  and public.current_newsroom_role() in ('admin','editor')
);

drop policy if exists "Newsroom updates own images" on storage.objects;
create policy "Newsroom updates own images" on storage.objects
for update to authenticated
using (bucket_id = 'news-media' and (storage.foldername(name))[1] = auth.uid()::text)
with check (bucket_id = 'news-media' and (storage.foldername(name))[1] = auth.uid()::text);

drop policy if exists "Newsroom deletes own images or admin" on storage.objects;
create policy "Newsroom deletes own images or admin" on storage.objects
for delete to authenticated
using (bucket_id = 'news-media' and ((storage.foldername(name))[1] = auth.uid()::text or public.current_newsroom_role() = 'admin'));

-- BOOTSTRAP ADMIN:
-- 1) Supabase Dashboard > Authentication > Users > Invite user (use your own email).
-- 2) Copy that user's UUID.
-- 3) Run the next statement manually, replacing UUID and name:
-- insert into public.profiles (id, full_name, role)
-- values ('PASTE-AUTH-USER-UUID-HERE', 'Nama Admin', 'admin')
-- on conflict (id) do update set full_name = excluded.full_name, role = 'admin';
--
-- For editors, invite their email and insert profile with role='editor'.
-- Never enable unrestricted public signup for this dashboard.
