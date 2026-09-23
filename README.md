# Arsip — UNAIR Repository to PDF

Web all-in-one untuk menyusun halaman pembaca repository UNAIR menjadi satu PDF. **Tanpa instal aplikasi VPN** — semua ditangani server.

## Arsitektur

```text
Browser → React/Vite di Vercel → FastAPI di Google Cloud Run
                               ├─ login portal eduVPN otomatis (wireproxy)
                               ├─ login OPAC dan akses halaman
                               └─ validasi semua gambar → PDF → unduhan
```

User cukup buka web, isi URL + kredensial kampus, klik Buat PDF. Server menangani VPN, download, dan penyusunan PDF.

## Deploy

### Frontend (Vercel)
1. Import repository di Vercel. Framework: Vite.
2. Atur `VITE_API_URL=https://backend-url.run.app`.
3. Deploy.

### Backend (Google Cloud Run)
```bash
gcloud run deploy unair-backend \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 1 \
  --timeout 300 \
  --set-env-vars "VPN_MODE=portal,ALLOWED_ORIGINS=https://your-vercel-url.vercel.app,APP_ACCESS_KEY=kuncirahasia123"
```

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
