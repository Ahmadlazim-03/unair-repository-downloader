# Arsip — UNAIR Repository to PDF

Web all-in-one untuk menyusun halaman pembaca repository UNAIR menjadi satu PDF. **Tanpa instal aplikasi VPN** — semua ditangani server.

## Arsitektur

```text
Browser → React/Vite di Vercel → FastAPI di Back4App Containers
                               ├─ login portal eduVPN otomatis (wireproxy)
                               ├─ login OPAC dan akses halaman
                               └─ validasi semua gambar → PDF → unduhan
```

User cukup buka web, isi URL + kredensial kampus, klik Buat PDF. Server menangani VPN, download, dan penyusunan PDF.

## Deploy

### Frontend (Vercel)
1. Import repository di Vercel. Framework: Vite.
2. Backend produksi: `https://unairrepositorydownloader-d6x2bsd9.b4a.run`. `buildCommand` pada `vercel.json` menetapkan `VITE_API_URL` saat build agar pengaturan lama di dashboard tidak mengarah ke backend sebelumnya. Jika pindah backend, perbarui URL di `vercel.json` dan fallback `src/main.tsx`.
3. Deploy.

### Backend (Back4App Containers)
1. Buka [containers.back4app.com](https://containers.back4app.com)
2. Create App → GitHub → pilih repo `unair-repository-downloader`
3. Port: 7860
4. Env: `VPN_MODE=portal`, `ALLOWED_ORIGINS=https://NAMA-APP.vercel.app`, `APP_ACCESS_KEY=<kode-akses-pribadi-minimal-8-karakter>`.
5. Gunakan `Dockerfile` di root proyek dan satu instance backend. Docker memasang Wireproxy 1.0.8 sesuai arsitektur CPU dan memeriksa SHA-256 binary.

Backend membutuhkan koneksi UDP keluar menuju endpoint VPN kampus. Listener SOCKS5 yang berhasil berjalan belum membuktikan handshake VPN berhasil. Jika platform hosting menolak UDP, backend perlu dipindahkan ke host yang mengizinkannya; frontend tetap dapat berada di Vercel.

### Lokal (Windows)
Prasyarat: Node.js 22+, Python 3.11+, VPN UNAIR aktif.

```powershell
.\scripts\install.ps1
.\scripts\start-local.ps1
```

## Pemeriksaan dan perbaikan Wireproxy

Setelah memperbarui kode, **rebuild/redeploy backend Back4App**. Redeploy frontend saja tidak memperbarui kode VPN. Port Back4App adalah `7860`; Docker Compose lokal memakai `8787` dengan `PORT=8787`.

- `/health` sekarang menyertakan `vpn_engine`, `wireproxy_available`, dan `message`. Pada mode portal, binary yang tidak ditemukan menghasilkan status `vpn_unavailable`.
- DNS dari portal dapat berisi alamat IP sekaligus domain pencarian. Wireproxy hanya menerima IP untuk kolom DNS; converter menyaring domain pencarian tersebut. Format keepalive memakai `PersistentKeepalive`, mengikuti [parser Wireproxy 1.0.8](https://github.com/windtf/wireproxy/blob/v1.0.8/config.go).
- Konfigurasi diuji dengan `wireproxy -n` sebelum dijalankan. SOCKS5 memakai port kosong dan diuji dengan handshake SOCKS5. Output proses dibaca terus agar pipe tidak penuh saat unduhan panjang.
- Pesan kegagalan membedakan validasi konfigurasi, startup, DNS endpoint, dan penolakan izin platform. Log tidak menyalin konfigurasi, key, atau password.
- Baris `INFO: Application startup complete` / `Uvicorn running ...` adalah startup normal, meskipun dashboard menampilkannya dalam kategori error karena berasal dari stderr.
- Konfigurasi VPN akun lain tidak dihapus otomatis ketika kuota portal penuh. Hanya konfigurasi yang dibuat oleh proses ini yang dibersihkan.

Jalankan pemeriksaan backend dan frontend:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
npm.cmd run build
```

Untuk menguji dengan binary Wireproxy asli, pasang rilis resmi 1.0.8 dan atur `WIREPROXY_BIN` ke path executable sebelum menjalankan tests. Tiga pengujian binary akan dilewati jika binary tidak tersedia. Pengujian memakai key dummy dan endpoint localhost: tidak membutuhkan kredensial kampus. Pengujian ini mencakup reproduksi DNS yang ditolak, validasi konfigurasi, startup SOCKS5, dua tunnel bersamaan, serta penghapusan file sementara. Tes API memeriksa alur sampai unduhan PDF dengan respons repository simulasi.

Verifikasi langsung koneksi VPN kampus dan unduhan dari Back4App tetap perlu dilakukan setelah redeploy, menggunakan akun yang berhak mengakses dokumen. Pengujian lokal tidak membuktikan akses UDP dari jaringan Back4App.

## Keamanan
- Kredensial hanya dipakai dalam memori untuk login, tidak disimpan ke disk/database.
- Konfigurasi WireGuard sementara berisi key VPN; disimpan dengan izin terbatas dan dihapus setelah proses selesai. Binary dipasang saat build, bukan diunduh ketika user mengirim kredensial.
- URL dibatasi ke `ir.unair.ac.id` dan `eduvpn.unair.ac.id`.
- Hasil otomatis dihapus setelah 30 menit.
- Salinan PDF permanen dinonaktifkan secara default. Jika operator mengatur `OUTPUT_DIR`, salinan di folder itu perlu dikelola sendiri dan tidak mengikuti masa simpan sementara.
- PDF gambar, bukan PDF asli.

Proyek independen, tidak berafiliasi dengan UNAIR.
