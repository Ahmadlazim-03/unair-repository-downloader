import React, { useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowDownToLine, ArrowRight, BookOpen, Check, CheckCircle2, ChevronDown, CircleHelp, FileText, Link2, LoaderCircle, LockKeyhole, ShieldCheck, Trash2, Wifi, X } from 'lucide-react';
import './style.css';

const REPO = 'https://ir.unair.ac.id';
const stages = [
  { id: 'parse', name: 'Analisis halaman' },
  { id: 'download', name: 'Unduh gambar' },
  { id: 'assemble', name: 'Susun PDF' },
];

type Progress = {
  state: string;
  message: string;
  current: number;
  total: number;
};

/** Validate URL is ir.unair.ac.id viewer or catalog */
function validateUrl(url: string): string {
  try {
    const u = new URL(url);
    if (u.protocol !== 'https:' || u.hostname !== 'ir.unair.ac.id')
      throw new Error('URL harus dari https://ir.unair.ac.id');
    if (
      u.pathname === '/opac/detail-opac' ||
      (u.pathname.startsWith('/uploaded_files/') && u.pathname.endsWith('/index.html'))
    )
      return url;
    throw new Error('Masukkan URL detail katalog (/opac/detail-opac?id=…) atau URL pembaca (…/index.html).');
  } catch (e) {
    if (e instanceof Error && e.message.startsWith('URL harus')) throw e;
    if (e instanceof Error && e.message.startsWith('Masukkan')) throw e;
    throw new Error('URL tidak valid.');
  }
}

/** Fetch page as text with CORS proxy fallback. User must be on VPN. */
async function fetchText(url: string, signal?: AbortSignal): Promise<string> {
  const r = await fetch(url, {
    signal,
    credentials: 'omit',
    cache: 'no-store',
    referrerPolicy: 'no-referrer',
  });
  if (!r.ok) throw new Error(`HTTP ${r.status} saat mengakses ${new URL(url).pathname}`);
  return r.text();
}

async function fetchBlob(url: string, signal?: AbortSignal): Promise<Blob> {
  const r = await fetch(url, {
    signal,
    credentials: 'omit',
    cache: 'no-store',
    referrerPolicy: 'no-referrer',
  });
  if (!r.ok) throw new Error(`HTTP ${r.status} saat mengambil gambar`);
  return r.blob();
}

/** Extract viewer URL from catalog page HTML */
function extractViewerUrl(html: string, baseUrl: string): string {
  const matches = html.match(/['"]([^'"<>]*uploaded_files\/[^'"<>]*?\/index\.html(?:\?[^'"<>]*)?)['"]/g);
  if (!matches) throw new Error('Tidak ditemukan tautan pembaca di halaman katalog. Pastikan dokumen tersedia dan Anda sudah login.');
  const urls: string[] = [];
  for (const m of matches) {
    const raw = m.slice(1, -1).replace(/\\\//g, '/');
    try {
      const full = new URL(raw, baseUrl).href;
      if (new URL(full).hostname === 'ir.unair.ac.id') urls.push(full);
    } catch { /* skip invalid */ }
  }
  if (urls.length === 0) throw new Error('Tautan pembaca tidak ditemukan di halaman detail.');
  // deduplicate
  const unique = [...new Set(urls)];
  if (unique.length > 1) throw new Error('Katalog memiliki beberapa dokumen. Buka dokumen yang diinginkan dan gunakan URL index.html-nya.');
  return unique[0];
}

/** Parse FlipHTML5 config.js for page count and image path */
function parseConfig(source: string, maximum = 500): { count: number; path: string } {
  const counts = [...source.matchAll(/bookConfig\.totalPageCount\s*=\s*["']?(\d+)/g)];
  if (!counts.length) throw new Error('Format pembaca tidak didukung: jumlah halaman tidak ditemukan.');
  const count = parseInt(counts[counts.length - 1][1], 10);
  if (count < 1 || count > maximum) throw new Error(`Jumlah halaman (${count}) di luar batas 1–${maximum}.`);
  const paths = [...source.matchAll(/bookConfig\.normalPath\s*=\s*["']([^"']+)["']/g)];
  const path = paths.length ? paths[paths.length - 1][1] : 'files/mobile/';
  if (path.includes('..') || !path.startsWith('files/')) throw new Error('Lokasi gambar tidak didukung.');
  return { count, path };
}

/** Build PDF from page images using jsPDF */
async function buildPdf(
  images: Blob[],
  title: string,
  update: (msg: string) => void
): Promise<Blob> {
  update('Memuat library PDF...');
  // Dynamic import jsPDF
  const { jsPDF } = await import('jspdf');

  let doc: InstanceType<typeof jsPDF> | null = null;

  for (let i = 0; i < images.length; i++) {
    update(`Menyusun halaman ${i + 1} dari ${images.length}...`);
    const blob = images[i];
    const dataUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = () => reject(new Error(`Gagal membaca halaman ${i + 1}`));
      reader.readAsDataURL(blob);
    });

    // Get image dimensions
    const dims = await new Promise<{ w: number; h: number }>((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve({ w: img.naturalWidth, h: img.naturalHeight });
      img.onerror = () => reject(new Error(`Halaman ${i + 1} bukan gambar valid.`));
      img.src = dataUrl;
    });

    if (dims.w < 50 || dims.h < 50) throw new Error(`Halaman ${i + 1} terlalu kecil.`);

    // A4-ish aspect: use image aspect ratio, 595.28 pt width
    const pdfWidth = 595.28;
    const pdfHeight = pdfWidth * (dims.h / dims.w);

    if (i === 0) {
      doc = new jsPDF({ unit: 'pt', format: [pdfWidth, pdfHeight] });
    } else {
      doc!.addPage([pdfWidth, pdfHeight]);
    }

    const format = blob.type === 'image/png' ? 'PNG' : 'JPEG';
    doc!.addImage(dataUrl, format, 0, 0, pdfWidth, pdfHeight);
  }

  if (!doc) throw new Error('Tidak ada halaman untuk disusun.');
  doc.setProperties({ title, creator: 'Arsip Repository (client-side)' });
  return doc.output('blob');
}

function App() {
  const [url, setUrl] = useState('');
  const [progress, setProgress] = useState<Progress | null>(null);
  const [error, setError] = useState('');
  const [pdfBlob, setPdfBlob] = useState<Blob | null>(null);
  const [pdfTitle, setPdfTitle] = useState('');
  const [pdfPages, setPdfPages] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const active = !!progress && !['done', 'error'].includes(progress.state);
  const done = progress?.state === 'done';
  const terminalError = progress?.state === 'error';
  const stage = done ? 3 : stages.findIndex(s => s.id === progress?.state);
  const percentage = done ? 100 : progress?.total ? Math.round((progress.current / progress.total) * 90) : 0;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (active) return;
    setError('');
    setPdfBlob(null);
    setPdfTitle('');
    setPdfPages(0);
    const ac = new AbortController();
    abortRef.current = ac;

    try {
      const validUrl = validateUrl(url);
      setProgress({ state: 'parse', message: 'Menganalisis halaman...', current: 0, total: 0 });

      let viewerUrl: string;
      if (validUrl.includes('/uploaded_files/') && validUrl.endsWith('/index.html')) {
        viewerUrl = validUrl;
      } else {
        // Catalog page: fetch and extract viewer link
        const html = await fetchText(validUrl, ac.signal);
        viewerUrl = extractViewerUrl(html, validUrl);
      }

      // Get base URL for viewer
      const base = viewerUrl.replace(/\/index\.html.*$/, '/');

      // Fetch config.js
      const configUrl = base + 'mobile/javascript/config.js';
      const configText = await fetchText(configUrl, ac.signal);
      const { count, path } = parseConfig(configText);

      // Extract title from viewer page
      let title = 'Dokumen UNAIR';
      try {
        const viewerHtml = await fetchText(viewerUrl, ac.signal);
        const titleMatch = viewerHtml.match(/<title[^>]*>([^<]+)<\/title>/i);
        if (titleMatch) title = titleMatch[1].trim();
      } catch { /* use default */ }

      setPdfTitle(title);
      setProgress({ state: 'download', message: `Mengunduh halaman 1 dari ${count}...`, current: 0, total: count });

      // Download all pages sequentially
      const images: Blob[] = [];
      for (let i = 1; i <= count; i++) {
        if (ac.signal.aborted) throw new Error('Proses dibatalkan.');
        setProgress({ state: 'download', message: `Mengunduh halaman ${i} dari ${count}...`, current: i, total: count });
        const imgUrl = base + path + i + '.jpg';
        let blob: Blob | null = null;
        for (let attempt = 0; attempt < 3; attempt++) {
          try {
            blob = await fetchBlob(imgUrl, ac.signal);
            break;
          } catch (e) {
            if (attempt === 2) throw e;
            await new Promise(r => setTimeout(r, 500 * (attempt + 1)));
          }
        }
        if (!blob || blob.size < 100) throw new Error(`Halaman ${i} gagal diunduh atau terlalu kecil.`);
        if (!blob.type.startsWith('image/')) throw new Error(`Halaman ${i} bukan gambar (${blob.type}). Mungkin perlu login atau VPN belum terhubung.`);
        images.push(blob);
      }

      // Build PDF
      setProgress({ state: 'assemble', message: 'Menyusun PDF...', current: count, total: count });
      const pdf = await buildPdf(images, title, (msg) => {
        setProgress(p => p ? { ...p, message: msg } : p);
      });

      setPdfBlob(pdf);
      setPdfPages(count);
      setProgress({ state: 'done', message: 'PDF siap diunduh!', current: count, total: count });
    } catch (e) {
      if (ac.signal.aborted) {
        setProgress({ state: 'error', message: 'Proses dibatalkan.', current: 0, total: 0 });
      } else {
        const msg = e instanceof Error ? e.message : 'Terjadi kesalahan.';
        setError(msg);
        setProgress({ state: 'error', message: msg, current: 0, total: 0 });
      }
    } finally {
      abortRef.current = null;
    }
  }

  function cancel() {
    abortRef.current?.abort();
    setProgress(null);
    setPdfBlob(null);
    setError('');
  }

  function save() {
    if (!pdfBlob) return;
    const objectUrl = URL.createObjectURL(pdfBlob);
    const a = document.createElement('a');
    a.href = objectUrl;
    const clean = pdfTitle.replace(/[^a-zA-Z0-9 ._-]/g, '').trim() || 'dokumen-unair';
    a.download = `${clean}.pdf`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
  }

  return <div className="app-shell">
    <header><a href="/" className="brand"><span className="brand-mark"><BookOpen size={21}/></span>arsip<span className="brand-dot">.</span></a><span className="header-note">REPOSITORY TO PDF</span><a className="help-link" href="#cara-kerja"><CircleHelp size={16}/> Cara kerja</a></header>
    <main>
      <section className="intro"><div className="eyebrow"><span/> UNTUK RUANG BELAJAR ANDA</div><h1>Dari repository,<br/>ke ruang baca Anda<span>.</span></h1><p>Simpan dokumen UNAIR yang dapat Anda akses menjadi satu PDF. Semua halaman, tersusun dalam satu tempat.</p></section>
      <div className="workspace">
        <section className="form-card">
          <div className="card-heading"><div className="icon-tile"><FileText size={22}/></div><div><h2>Siapkan dokumen Anda</h2><p>Mulai dengan tautan dari repository.</p></div><span className="step-tag">01 — INPUT</span></div>
          <form onSubmit={submit}>
            <fieldset disabled={active}>
              <label htmlFor="url">Tautan dokumen <span>*</span></label>
              <div className="input-icon"><Link2 size={17}/><input id="url" type="url" placeholder="https://ir.unair.ac.id/opac/detail-opac?id=…" value={url} onChange={e => setUrl(e.target.value)} required maxLength={2048}/></div>
              <p className="field-help">Gunakan URL detail katalog atau halaman pembaca <code>index.html</code>.</p>
              <div className="divider"/>
              <div className="vpn-notice">
                <Wifi size={18}/>
                <div>
                  <strong>Pastikan VPN eduVPN kampus sudah terhubung</strong>
                  <p>Browser Anda harus terhubung ke jaringan UNAIR via eduVPN untuk mengakses dokumen. Tanpa VPN, gambar halaman tidak dapat diunduh.</p>
                </div>
              </div>
              <div className="privacy-note"><ShieldCheck size={18}/><p>Semua proses berjalan di browser Anda. Tidak ada data yang dikirim ke server lain. Kredensial tidak diperlukan — cukup VPN aktif.</p></div>
              <button className="primary" disabled={active} type="submit">{active ? <><LoaderCircle className="spin" size={18}/> Sedang memproses…</> : <>Buat PDF <ArrowRight size={18}/></>}</button>
            </fieldset>
            <p className="consent-note">Gunakan untuk dokumen yang berhak Anda akses dan simpan.</p>
          </form>
        </section>
        <aside className="output-card">
          <div className="output-top"><h2>Ruang unduhan</h2><span className="step-tag">02 — OUTPUT</span></div>
          {!progress ? <div className="empty-state"><div className="paper-stack"><div className="paper back"/><div className="paper front"><FileText size={35}/><span/><span/><span/></div><span className="pdf-badge">PDF</span></div><h3>Satu dokumen. Siap dibaca.</h3><p>Progres dan hasil unduhan<br/>akan muncul di sini.</p><div className="empty-tags"><span><Check size={13}/> Urutan asli</span><span><Check size={13}/> Semua halaman tersedia</span></div></div> : <div className="job-panel" aria-live="polite">
            {done ? <>
              <div className="success-icon"><CheckCircle2 size={32}/></div>
              <h3>Dokumen siap.</h3>
              <p className="document-title">{pdfTitle}</p>
              <div className="file-info"><FileText size={24}/><div><strong>{pdfTitle.replace(/[^a-zA-Z0-9 ._-]/g, '').trim() || 'dokumen-unair'}.pdf</strong><small>{pdfPages} halaman · {pdfBlob ? (pdfBlob.size / 1048576).toFixed(1) : '?'} MB</small></div><span>PDF</span></div>
              <p className="field-help">PDF gambar, sesuai tampilan pembaca. Teks belum dapat diedit atau dicari.</p>
              <button className="primary" onClick={save}><ArrowDownToLine size={18}/> Unduh PDF</button>
            </> : <>
              <div className={`progress-icon ${terminalError ? 'failed' : ''}`}>{terminalError ? <X size={26}/> : <LoaderCircle size={28} className="spin"/>}</div>
              <h3>{terminalError ? 'Proses berhenti' : 'Menyiapkan bacaan Anda'}</h3>
              <p className="progress-message">{progress?.message || 'Memulai...'}</p>
              <div className="progress-track"><span style={{ width: `${percentage}%` }}/></div>
              <div className="progress-caption"><span>{progress?.current || 0} / {progress?.total || '—'} halaman</span><strong>{percentage}%</strong></div>
              <ol className="stages">{stages.map((s, i) => <li key={s.id} className={i < stage ? 'complete' : i === stage ? 'current' : ''}><span>{i < stage ? <Check size={13}/> : i + 1}</span>{s.name}</li>)}</ol>
            </>}
            <button className="text-button" onClick={cancel}><Trash2 size={14}/>{done ? 'Hapus hasil' : terminalError ? 'Tutup' : 'Batalkan proses'}</button>
          </div>}
          <div className="output-footer"><LockKeyhole size={15}/><span>100% di browser Anda · tidak ada server · data tidak dikirim</span></div>
        </aside>
      </div>
      {error && <div role="alert" className="error-banner"><CircleHelp size={18}/><span>{error}</span></div>}
      <div className="connection-bar"><span className="status-dot online"/><span>Mode client-side · menggunakan koneksi VPN dari perangkat Anda</span><span className="connection-detail"><Wifi size={14}/> Tanpa server backend</span></div>
      <section id="cara-kerja" className="how"><div><span className="eyebrow">ALUR SEDERHANA</span><h2>Dari tautan menjadi arsip.</h2></div><div className="how-steps"><article><span>01</span><h3>Hubungkan VPN</h3><p>Instal eduVPN di perangkat Anda dan hubungkan ke jaringan UNAIR.</p></article><article><span>02</span><h3>Tempel tautan</h3><p>Salin URL dokumen dari repository UNAIR ke form di atas.</p></article><article><span>03</span><h3>Simpan PDF</h3><p>Browser mengunduh semua halaman dan menyusunnya menjadi satu PDF.</p></article></div></section>
      <details className="faq"><summary>Apakah ini mengunduh PDF asli? <ChevronDown size={16}/></summary><p>Aplikasi menyusun ulang halaman gambar yang disediakan pembaca repository. Hasil mengikuti resolusi sumber, bukan file PDF asli atau dokumen Word. Jika ada halaman yang tidak dapat diambil, proses berhenti dan tidak menyajikan PDF yang kurang lengkap.</p></details>
      <details className="faq"><summary>Apakah data saya aman? <ChevronDown size={16}/></summary><p>Semua proses berjalan 100% di browser Anda. Tidak ada data, kredensial, atau dokumen yang dikirim ke server pihak ketiga. Web ini hanya berupa halaman statis yang di-host di Vercel.</p></details>
      <details className="faq"><summary>Kenapa harus pakai VPN? <ChevronDown size={16}/></summary><p>Dokumen di repository UNAIR hanya dapat diakses dari jaringan kampus. eduVPN menghubungkan perangkat Anda ke jaringan tersebut sehingga browser bisa mengunduh halaman dokumen.</p></details>
    </main>
    <footer><span className="brand small">arsip.</span><span>Proyek independen · bukan layanan resmi Universitas Airlangga</span><span>100% client-side · tanpa server backend.</span></footer>
  </div>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
