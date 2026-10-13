// Konfigurasi publik Supabase untuk Ruang Redaksi NusantaraNews.
// Isi dengan Project URL dan anon/publishable key dari Supabase Dashboard > Project Settings > API.
// Aman untuk frontend HANYA jika Row Level Security dan policies pada supabase/schema.sql sudah aktif.
// JANGAN pernah memasukkan service_role key atau password database ke file ini.
window.NN_SUPABASE_CONFIG = {
  url: "https://YOUR-PROJECT.supabase.co",
  anonKey: "YOUR-ANON-OR-PUBLISHABLE-KEY"
};
