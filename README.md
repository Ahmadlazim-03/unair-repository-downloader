# Arsip — UNAIR Repository to PDF (Client-Side)

Web berbahasa Indonesia untuk menyusun halaman pembaca repository UNAIR menjadi satu PDF. **100% berjalan di browser** — tanpa server backend.

## Cara Kerja

```text
Browser pengguna (VPN aktif)
  ├─ Fetch halaman detail / viewer dari ir.unair.ac.id
  ├─ Parse konfigurasi FlipHTML5 (jumlah halaman, path gambar)
  ├─ Download semua gambar halaman secara berurutan
  └─ Rakit menjadi PDF via jsPDF di memori browser → download
```

**Prasyarat pengguna**: Hubungkan eduVPN kampus di perangkat Anda sebelum membuka web ini.

## Deploy ke Vercel

1. Push repository ke GitHub.
2. Import di [vercel.com/new](https://vercel.com/new). Framework: Vite.
3. Deploy. Tidak perlu environment variable apapun.
4. Bagikan URL Vercel ke teman-teman Anda.

## Menjalankan Lokal

```bash
npm install
npm run dev
```

Buka **http://127.0.0.1:5173**. Pastikan eduVPN aktif di perangkat Anda.

## Keamanan & Privasi

- **100% client-side**: tidak ada data yang dikirim ke server selain ir.unair.ac.id.
- Tidak ada kredensial yang diminta — akses dokumen bergantung pada koneksi VPN pengguna.
- PDF dihasilkan di memori browser; tidak disimpan di server manapun.
- URL dibatasi ke domain `ir.unair.ac.id` saja.

## Batasan

- Output adalah **PDF gambar**, bukan PDF asli atau OCR.
- Browser harus terhubung ke jaringan UNAIR via eduVPN.
- Dokumen yang memerlukan login repository (NIM/password) mungkin tidak dapat diakses langsung dari browser karena CORS. Gunakan URL viewer `index.html` langsung jika tersedia.
- Maksimum 500 halaman per dokumen.

## Teknologi

- React 19 + Vite + TypeScript
- jsPDF (client-side PDF generation)
- Lucide React (icons)
- Deploy: Vercel (static site)

Proyek independen, tidak berafiliasi dengan UNAIR. Gunakan hanya untuk dokumen yang berhak Anda akses.
