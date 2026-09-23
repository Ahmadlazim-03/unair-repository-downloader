# Arsip — UNAIR Repository to PDF

Web all-in-one untuk menyusun halaman pembaca repository UNAIR menjadi satu PDF. **Tanpa instal aplikasi VPN** — semua ditangani server.

## Arsitektur

```text
Browser → React/Vite + FastAPI dalam satu container Render
          ├─ login portal eduVPN otomatis (wireproxy)
          ├─ login OPAC dan akses halaman
          └─ validasi semua gambar → PDF → unduhan
```

User cukup buka web, isi URL + kredensial kampus, klik Buat PDF. Server menangani VPN, download, dan penyusunan PDF.

## Deploy

### Render (frontend dan backend)
1. Masuk ke Render CLI (`render login`) dan pilih workspace (`render workspace set`).
2. Pastikan akun Render mengizinkan pembuatan Web Service. Akun ini menerima respons `402 Payment information is required` saat mencoba membuat layanan paket `free` pada 2026-09-23. Metode pembayaran harus diatur sendiri di [Render Billing](https://dashboard.render.com/billing); jangan memasukkan data kartu ke repo atau chat.
3. Jalankan `powershell -ExecutionPolicy Bypass -File .\scripts\deploy-render.ps1` dari root proyek. Script membuat satu Web Service Docker paket Free di region Singapore, mengatur `VPN_MODE=portal`, health check `/health`, dan menyimpan kode akses acak di `.runtime/render-app-key.txt` yang tidak masuk Git.
4. Setelah URL Render aktif, jalankan `scripts/check-production.py --api https://NAMA-LAYANAN.onrender.com --url URL_KATALOG --expected-pages JUMLAH_HALAMAN` dengan Python dari `.venv` untuk memverifikasi akses VPN, login katalog, PDF, dan cleanup secara nyata.

Image Docker membangun React/Vite, lalu FastAPI menyajikan frontend dan API pada satu origin. URL `onrender.com` tidak memiliki masa kedaluwarsa satu jam seperti URL Back4App yang dipakai sebelumnya. Paket Free [tidur setelah 15 menit tanpa trafik](https://render.com/docs/free), sehingga kunjungan pertama dapat menunggu sekitar satu menit. Penyimpanan lokal container bersifat sementara; hasil PDF proyek ini memang dihapus setelah 30 menit. Backend membutuhkan UDP keluar ke endpoint VPN kampus. Startup Wireproxy saja belum membuktikan handshake VPN berhasil; langkah 4 wajib sebelum layanan dianggap siap.

### Lokal (Windows)
Prasyarat: Node.js 22+, Python 3.11+, VPN UNAIR aktif.

```powershell
.\scripts\install.ps1
.\scripts\start-local.ps1
```

## Pemeriksaan dan perbaikan Wireproxy

Versi ini ditandai dengan `"revision":"repository-tls-4"` dan `"wireproxy_version":"1.1.3"` pada `/health`. Jika field ini belum muncul, periksa apakah Render sudah membangun commit terbaru dari branch `main`.

Uji langsung 2026-09-23 menemukan rantai HTTPS repository yang tidak cocok: leaf `*.unair.ac.id` diterbitkan Sectigo DV R36, tetapi server mengirim intermediate lama. Aplikasi melengkapi issuer R36 resmi, menggunakan root certifi, dan tetap memverifikasi hostname, tanggal, serta rantai lengkap ke root terpercaya. Detail sumber dan hash ada di `backend/certs/README.md`. Endpoint login modal INLISLite juga diarahkan ke `/opac/site/loginanggota`, sesuai alur AJAX situs. Profil TCP yang membutuhkan ProxyGuard tidak ditawarkan sebagai profil Wireproxy UDP.

Untuk memeriksa produksi secara nyata, gunakan `scripts/check-production.py --api URL_RENDER --url URL_KATALOG --expected-pages 93` dengan Python dari `.venv`. Skrip meminta kredensial tanpa menampilkannya, login ke backend, menunggu PDF, memverifikasi jumlah/gambar setiap halaman dan cleanup, menyimpan PDF serta laporan tanpa kredensial di `.runtime`, lalu menghapus hasil uji dari server. Parameter jumlah halaman harus sesuai dokumen yang diuji.

Hasil uji nyata Back4App pada 2026-09-23, revisi `repository-tls-4`: login portal, tunnel UDP, login katalog, pengambilan halaman, penyusunan dan unduhan PDF berhasil. Dokumen contoh memiliki 93 halaman / 18.707.971 byte; proses selesai dalam 82,8 detik tanpa peringatan cleanup. Ke-93 gambar halaman unik dan cocok berurutan dengan hasil lokal. Laporan dan PDF tersimpan lokal di `.runtime/production-verified.json` / `.runtime/production-verified.pdf` (tidak masuk Git). Hasil ini membuktikan alur dokumen tersebut; masa aktif hosting tetap mengikuti paket/deployment operator.

Wireproxy 1.0.8 menerapkan aturan Landlock saat startup Linux yang dapat gagal jika path seperti `/dev/log` tidak ada pada image minimal. Pemeriksaan `--version` dan `--configtest` tidak menjalankan tahap tersebut. Rilis 1.1.3 memakai `IgnoreIfMissing()` pada aturan path tersebut ([kode upstream](https://github.com/windtf/wireproxy/blob/v1.1.3/cmd/wireproxy/main.go)); isolasi container dan Landlock tetap aktif.

Image sekarang menjalankan `python -m backend.vpn_selftest` ketika build dan sebelum API dijalankan. Tes ini memulai SOCKS5 menggunakan key sementara dan endpoint localhost, lalu membersihkannya. Pesan sukses: `Wireproxy runtime self-test passed (SOCKS5 and cleanup).` Ini memverifikasi startup pada host yang menjalankan container, belum memverifikasi handshake dengan VPN kampus. Workflow GitHub Actions juga membangun image Linux dan menjalankan tes di dalamnya.

Error runtime menampilkan bagian akhir output Wireproxy setelah key base64/hex dan nilai kolom sensitif disamarkan. Jika startup masih gagal, bagian `Detail:` membedakan masalah path Linux, izin platform, dan resource. Peringatan build `debconf: delaying package configuration, since apt-utils is not installed` tidak menunjukkan kegagalan Wireproxy.

Portal eduVPN mengarahkan penghapusan ke `home#active-configurations`. HTTP client membuang fragment tersebut sebelum request, sambil tetap memvalidasi HTTPS dan hostname. Cleanup memilih formulir `delete_config`/`deleteConfig` secara eksplisit, menghapus hanya konfigurasi sesi sendiri, dan memastikan namanya sudah hilang dari daftar aktif. Peringatan cleanup berarti penghapusan belum bisa dikonfirmasi; bukan bukti bahwa VPN atau penyusunan PDF gagal.

Setelah memperbarui kode, rebuild/redeploy layanan Render agar frontend dan backend diperbarui bersama. Render menyediakan `PORT` (umumnya `10000`); Docker Compose lokal memakai `8787` dengan `PORT=8787`.

- `/health` sekarang menyertakan `vpn_engine`, `wireproxy_available`, dan `message`. Pada mode portal, binary yang tidak ditemukan menghasilkan status `vpn_unavailable`.
- DNS dari portal dapat berisi alamat IP sekaligus domain pencarian. Wireproxy hanya menerima IP untuk kolom DNS; converter menyaring domain pencarian tersebut. Format keepalive memakai `PersistentKeepalive`, mengikuti [parser Wireproxy 1.1.3](https://github.com/windtf/wireproxy/blob/v1.1.3/config.go).
- Konfigurasi diuji dengan `wireproxy -n` sebelum dijalankan. SOCKS5 memakai port kosong dan diuji dengan handshake SOCKS5. Output proses dibaca terus agar pipe tidak penuh saat unduhan panjang.
- Pesan kegagalan membedakan validasi konfigurasi, startup, DNS endpoint, dan penolakan izin platform. Log tidak menyalin konfigurasi, key, atau password.
- Baris `INFO: Application startup complete` / `Uvicorn running ...` adalah startup normal, meskipun dashboard menampilkannya dalam kategori error karena berasal dari stderr.
- Konfigurasi VPN akun lain tidak dihapus otomatis ketika kuota portal penuh. Hanya konfigurasi yang dibuat oleh proses ini yang dibersihkan.

Jalankan pemeriksaan backend dan frontend:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm.cmd run build
```

Untuk menguji dengan binary Wireproxy asli, pasang rilis resmi 1.1.3 dan atur `WIREPROXY_BIN` ke path executable sebelum menjalankan tests. Tiga pengujian binary akan dilewati jika binary tidak tersedia. Pengujian memakai key dummy dan endpoint localhost: tidak membutuhkan kredensial kampus. Pengujian ini mencakup reproduksi DNS yang ditolak, validasi konfigurasi, startup SOCKS5, dua tunnel bersamaan, serta penghapusan file sementara. Tes API memeriksa alur sampai unduhan PDF dengan respons repository simulasi.

Verifikasi langsung koneksi VPN kampus dan unduhan dari Render tetap perlu dilakukan setelah deploy, menggunakan akun yang berhak mengakses dokumen. Pengujian lokal atau Back4App tidak membuktikan akses UDP dari jaringan Render.

## Keamanan
- Kredensial hanya dipakai dalam memori untuk login, tidak disimpan ke disk/database.
- Konfigurasi WireGuard sementara berisi key VPN; disimpan dengan izin terbatas dan dihapus setelah proses selesai. Binary dipasang saat build, bukan diunduh ketika user mengirim kredensial.
- URL dibatasi ke `ir.unair.ac.id` dan `eduvpn.unair.ac.id`.
- Hasil otomatis dihapus setelah 30 menit.
- Salinan PDF permanen dinonaktifkan secara default. Jika operator mengatur `OUTPUT_DIR`, salinan di folder itu perlu dikelola sendiri dan tidak mengikuti masa simpan sementara.
- PDF gambar, bukan PDF asli.

Proyek independen, tidak berafiliasi dengan UNAIR.
