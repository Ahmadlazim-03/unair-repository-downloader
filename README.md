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
2. Atur `VITE_API_URL=https://unairrepositorydownloader-zraxnpem.b4a.run`.
3. Deploy.

### Backend (Back4App Containers)
1. Buka [containers.back4app.com](https://containers.back4app.com)
2. Create App → GitHub → pilih repo `unair-repository-downloader`
3. Port: 7860
4. Env: `VPN_MODE=portal`, `ALLOWED_ORIGINS=*`, `APP_ACCESS_KEY=kuncirahasia123`

### Lokal (Windows)
Prasyarat: Node.js 22+, Python 3.11+, VPN UNAIR aktif.

```powershell
.\scripts\install.ps1
.\scripts\start-local.ps1
```

## Keamanan
- Kredensial hanya dipakai dalam memori untuk login, tidak disimpan ke disk/database.
- URL dibatasi ke `ir.unair.ac.id` dan `eduvpn.unair.ac.id`.
- Hasil otomatis dihapus setelah 30 menit.
- PDF gambar, bukan PDF asli.

Proyek independen, tidak berafiliasi dengan UNAIR.
