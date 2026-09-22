---
title: Unair Repository Downloader Backend
emoji: 📚
colorFrom: indigo
colorTo: blue
sdk: gradio
app_file: app.py
pinned: false
---

# Arsip — UNAIR Repository to PDF

Web berbahasa Indonesia untuk menyusun halaman pembaca repository UNAIR menjadi satu PDF gambar. Input: URL detail katalog / viewer dan kredensial kampus. Output: PDF dengan jumlah halaman sesuai konfigurasi viewer. Password, cookie, dan token tidak dimasukkan ke repository.

## Arsitektur dan status

```text
Browser → React/Vite di Vercel → FastAPI pada backend Linux/Docker
                               ├─ login portal eduVPN resmi
                               ├─ konfigurasi WireGuard sementara milik proses
                               ├─ login OPAC dan akses halaman yang diizinkan
                               └─ validasi semua gambar → PDF → unduhan bertoken
```

**Deploy frontend ke Vercel saja belum mengaktifkan VPN.** Versi ini membutuhkan backend Linux yang dapat menjalankan WireGuard (`NET_ADMIN`, kernel WireGuard, UDP keluar). Laptop pengguna tidak perlu memasang eduVPN jika backend tersebut tersedia. Vercel Sandbox adalah alternatif infrastruktur yang perlu pengujian VPN tersendiri; proyek ini **belum mengimplementasikan adapter Sandbox**.

Mode `existing` berjalan di Windows dan menggunakan VPN yang sudah aktif pada laptop untuk pengujian lokal. Mode `portal` membuat koneksi sendiri lewat form konfigurasi manual resmi eduVPN. Bila akun tidak diizinkan membuat konfigurasi, kuota penuh, ada SSO/MFA, atau profil bukan WireGuard, aplikasi berhenti dengan penjelasan. Tidak ada bypass login atau pemakaian client ID OAuth milik aplikasi lain.

## Menjalankan di Windows

Prasyarat: Node.js 22.12+ atau 24/25, Python 3.11+, VPN UNAIR aktif.

```powershell
cd C:\PROJECT_GITHUB\unair-repository-downloader
.\scripts\install.ps1
.\scripts\start-local.ps1
```

Buka **http://127.0.0.1:5173**. Masukkan URL dan akun melalui form. Untuk URL viewer yang sudah bisa diakses, akun boleh kosong di mode lokal. Skrip menjalankan proses tersembunyi dan menyimpan PID/log operasional di `.runtime/` (diabaikan Git). Aplikasi tidak mencatat badan request/password; jangan menyalakan logging HTTP debug.

Hentikan dengan `scripts\stop-local.ps1`. Skrip itu memeriksa PID dan command line agar hanya menghentikan proses milik proyek.

Cara manual:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8787 --no-access-log
# terminal kedua
npm run dev
```

## Deploy frontend di Vercel

1. Push **folder proyek ini** sebagai repository tersendiri. Jangan push direktori induk, `.env`, PDF, atau `.runtime`.
2. Import repository di Vercel. Framework Vite; build `npm run build`; output `dist` (sudah dalam `vercel.json`).
3. Atur `VITE_API_URL=https://backend-anda.example` lalu deploy/redeploy. Variabel `VITE_*` terlihat publik: jangan isi password/key di sana.
4. Backend harus HTTPS dan `ALLOWED_ORIGINS` harus persis origin deployment Anda, tanpa slash penutup. Tambahkan origin preview secara eksplisit bila dibutuhkan; tidak memakai wildcard.

## Backend Linux dengan VPN otomatis

Gunakan VPS/mesin Linux yang mendukung modul kernel WireGuard dan Docker Compose. Backend menjalankan satu job pada satu waktu agar rute/kredensial antar pengguna tidak bercampur. Untuk skala lebih besar, diperlukan isolasi per job dan antrean; jangan menaikkan jumlah worker Uvicorn pada versi ini.

```sh
cp .env.example .env
# Edit .env:
# APP_ACCESS_KEY=<kode acak minimal 24 karakter; bagikan hanya ke pengguna aplikasi>
# ALLOWED_ORIGINS=https://nama-proyek.vercel.app
docker compose up --build -d
```

`compose.yaml` memasang WireGuard otomatis di container, memberi `NET_ADMIN`, membatasi memori, dan menyimpan berkas sementara dalam tmpfs. Tidak menggunakan VPN/key aktif milik laptop. Compose hanya membuka port `127.0.0.1:8787`; pasang reverse proxy HTTPS di depan port ini. Contoh Caddy pada host Linux:

```caddy
backend-anda.example {
    request_body { max_size 16KB }
    reverse_proxy 127.0.0.1:8787
}
```

Kode akses aplikasi menjadi pembatas penggunaan backend; pengguna mengisinya di web. Ini versi untuk penggunaan terbatas, belum sistem akun publik/SSO, kuota per pengguna, atau mitigasi bot. Jangan mempublikasikan kode akses. Browser berkomunikasi langsung dengan backend sehingga PDF besar tidak melewati batas response Function Vercel.

Alur VPN:

- Login lewat `https://eduvpn.unair.ac.id/vpn-user-portal/` menggunakan form dan hidden field terbaru.
- Jika beberapa profil tersedia, pengguna memilih profil yang diberikan akun tersebut.
- Buat konfigurasi bernama `arsip-<acak>` melalui `addConfig`. Config diproses sebagai data: hanya key/alamat/endpoint yang divalidasi, tidak menjalankan hook dari config.
- Arahkan hanya IP IPv4 repository ke tunnel. Tidak mengganti default route/DNS server atau mengambil kunci VPN laptop.
- Setelah proses, matikan tunnel, cabut konfigurasi **dengan nama proses itu saja**, lalu tutup sesi portal. Jika pembersihan tunnel gagal, worker menolak job berikutnya sampai direstart.

Host perlu dapat meresolusi `ir.unair.ac.id` sebelum mengaktifkan tunnel. Implementasi belum mendukung repository dengan DNS privat saja/IPv6 saja, profil OpenVPN-only, SSO, MFA, atau konfigurasi manual yang dinonaktifkan kampus. Pemutusan listrik/kill paksa dapat meninggalkan konfigurasi portal sampai kedaluwarsa; hapus entri `arsip-*` yang sesuai melalui portal resmi jika diperlukan.

## Keamanan, hasil, dan batas

- Input URL dibatasi ke detail/viewer `ir.unair.ac.id`; semua redirect diverifikasi sebelum diikuti. Request portal dibatasi ke `eduvpn.unair.ac.id`. Verifikasi TLS tetap aktif.
- Password dipakai dalam memori untuk login dan dibuang setelahnya; tidak disimpan ke disk/database/localStorage. Seperti aplikasi Python/JavaScript lain, ini bukan jaminan zeroization memori fisik.
- Token job acak dikirim dalam header Authorization, bukan query URL. Hasil hanya bisa diunduh dengan token job tersebut. Token hanya disimpan di memori tab; reload akan menghilangkan akses, hasil dibersihkan otomatis.
- Hasil disimpan maksimal 30 menit sejak job dibuat; tombol hapus mempercepat pembersihan. Job yang melewati TTL dibatalkan, file dihapus setelah proses berhenti. Maksimum 8 hasil sementara, 500 halaman, 250 MB sumber per dokumen (dapat dikonfigurasi).
- Halaman diunduh berurutan; hanya gangguan transport diulang maksimal 3 kali. Satu gambar hilang/tidak valid menggagalkan keseluruhan PDF. Tidak menampilkan hasil parsial sebagai dokumen lengkap.
- Output adalah **PDF gambar**, bukan PDF sumber asli, DOCX, atau OCR. Resolusi mengikuti gambar viewer. Aplikasi tidak mendekripsi dokumen atau mencari file yang tidak diberikan oleh layanan kampus.
- Adapter viewer mendukung pola FlipHTML5 `bookConfig.totalPageCount`, `normalPath`, `files/mobile/N.jpg`. Perubahan HTML login/reader dapat memerlukan pembaruan adapter.
- Katalog dengan beberapa tautan dokumen meminta URL viewer yang dipilih pengguna; tidak menggabungkan file yang berbeda tanpa pilihan.

## Pengujian

```powershell
npm run build
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tes menggunakan respons sintetis untuk redirect, kredensial, parser, gambar rusak, kelengkapan PDF, kontrol token, dan pembatalan. Uji nyata mode lokal dapat dijalankan lewat web saat VPN aktif. Keberhasilan mode lokal tidak membuktikan provisioning WireGuard berhasil di VPS/cloud; itu harus diuji pada host tujuan dan akun yang diizinkan.

## Referensi implementasi

- [eduVPN portal resmi, form konfigurasi manual](https://github.com/eduvpn/vpn-user-portal/blob/v3/views/manualConfiguration.php)
- [eduVPN API dan autentikasi OAuth](https://docs.eduvpn.org/server/v3/api.html)
- [Vercel: deploy Vite](https://vercel.com/docs/frameworks/frontend/vite)
- [Vercel Sandbox](https://vercel.com/docs/sandbox)

Proyek independen, tidak berafiliasi dengan UNAIR. Gunakan hanya dengan akun dan dokumen yang Anda berhak akses dan simpan. Dependensi memiliki lisensinya masing-masing; PyMuPDF tersedia dengan ketentuan AGPL atau lisensi komersial dari penyedianya.
