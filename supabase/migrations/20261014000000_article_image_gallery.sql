-- Add optional per-article gallery images without changing existing photo fields.
alter table public.articles
  add column if not exists image_urls jsonb not null default '[]'::jsonb,
  add column if not exists image_captions jsonb not null default '[]'::jsonb;
alter table public.articles
  drop constraint if exists articles_image_urls_gallery_limit,
  add constraint articles_image_urls_gallery_limit check (jsonb_typeof(image_urls) = 'array' and jsonb_array_length(image_urls) <= 2),
  drop constraint if exists articles_image_captions_gallery_limit,
  add constraint articles_image_captions_gallery_limit check (jsonb_typeof(image_captions) = 'array' and jsonb_array_length(image_captions) <= 2);
