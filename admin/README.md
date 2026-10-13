# Ruang Redaksi NusantaraNews — Setup Supabase

Dashboard: https://webpageds.github.io/nusantara-news-baru/admin/

## Fitur pada tahap ini
- Login Supabase Auth (tanpa pendaftaran publik).
- Peran admin dan editor/penulis yang dibaca dari tabel profiles.
- Buat dan edit berita, kategori, ringkasan, isi, sumber, slug, dan keterangan foto.
- Simpan draft; tombol terbitkan hanya terlihat bagi admin.
- Upload foto ke Supabase Storage dan media library.
- Pratinjau visual kartu tautan, salin teks, dan buka WhatsApp.
- RLS database untuk membatasi akses berdasarkan peran dan pemilik naskah.

## Setup pertama kali
1. Buat project di https://supabase.com/.
2. Buka SQL Editor dan jalankan seluruh file `supabase/schema.sql`.
3. Buka Authentication → Users → Invite user, lalu undang email admin.
4. Setelah user dibuat, salin UUID user dari Authentication → Users. Jalankan query bootstrap admin di bagian akhir `supabase/schema.sql` dengan UUID dan nama admin yang benar.
5. Untuk anggota redaksi, undang user dari Authentication, lalu tambahkan baris ke `public.profiles` dengan UUID yang sesuai, nama, dan role `editor`. Tetapkan role `admin` hanya untuk pengelola yang dipercaya.
6. Buka Project Settings → API (atau API Keys), salin Project URL dan anon/publishable key.
7. Edit `admin/config.js` di repository: ganti `YOUR-PROJECT` dan `YOUR-ANON-OR-PUBLISHABLE-KEY`, lalu commit. Key anon/publishable boleh berada di frontend **hanya** karena RLS di database/storage membatasi operasi. Jangan pernah menaruh `service_role` key di website.
8. Buka URL dashboard, login dengan akun undangan, lalu coba simpan draft dan unggah foto.

## Penting tentang publikasi website

Homepage dan halaman artikel memiliki jalur integrasi opsional ke Supabase. Setelah URL/key di \`admin/config.js\` diisi dan schema/RLS berhasil dipasang, berita berstatus \`published\` dari Supabase akan ikut tampil di homepage dan dapat dibuka melalui halaman artikel dinamis. Berita lama dari \`data/news.json\` tetap menjadi fallback, sehingga situs tidak kehilangan konten saat Supabase belum dikonfigurasi.

**Batasan preview WhatsApp:** kartu pratinjau di dashboard dan teks WhatsApp sudah tersedia, tetapi crawler WhatsApp biasanya tidak menjalankan JavaScript. Karena itu artikel baru dari Supabase belum dijamin mendapat judul/foto unik pada kartu tautan WhatsApp. Untuk metadata sosial unik yang konsisten, tahap berikutnya perlu membangkitkan halaman HTML statis untuk artikel baru atau menambahkan layanan server-side yang mengembalikan Open Graph sesuai slug.

## Keamanan
- Jangan simpan password atau service-role key di file apa pun.
- Nonaktifkan public signups pada Authentication settings; gunakan Invite user.
- RLS wajib aktif; jangan memberi akses admin melalui UI publik.
- Foto dalam bucket `news-media` dapat dibaca publik agar dapat ditampilkan di artikel. Upload dibatasi ke pengguna redaksi terautentikasi.
