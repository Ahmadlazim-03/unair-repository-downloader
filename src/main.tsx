import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowDownToLine, ArrowRight, BookOpen, Check, CheckCircle2, ChevronDown, CircleHelp, FileText, KeyRound, Link2, LoaderCircle, LockKeyhole, ShieldCheck, Trash2, Wifi, X } from 'lucide-react';
import './style.css';

const API = (import.meta.env.VITE_API_URL || 'https://unairrepositorydownloader-zraxnpem.b4a.run').replace(/\/$/, '');
type Health = {vpn_mode: string; access_key_required: boolean; retention_seconds: number; status: string};
type Ticket = {id: string; token: string; expires_at: number};
type Progress = {state: string; message: string; current: number; total: number; warning?: string; result?: {pages: number; bytes: number; title: string}; expires_at: number};
type Profile = {id: string; name: string};
const stages = [{id:'vpn',name:'Koneksi kampus'}, {id:'auth',name:'Akses dokumen'}, {id:'download',name:'Ambil halaman'}, {id:'assemble',name:'Susun PDF'}];

async function request(path: string, options: RequestInit = {}) {
  const response = await fetch(API + path, { ...options, cache:'no-store', referrerPolicy:'no-referrer' });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `Backend mengembalikan HTTP ${response.status}.`);
  }
  return response;
}

function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState('');
  const [url, setUrl] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [accessKey, setAccessKey] = useState('');
  const [sameAccount, setSameAccount] = useState(true);
  const [vpnUsername, setVpnUsername] = useState('');
  const [vpnPassword, setVpnPassword] = useState('');
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [profile, setProfile] = useState('');
  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [now, setNow] = useState(Date.now());
  const latestTicket = useRef<Ticket | null>(null);
  const active = busy || (!!ticket && !['done','error','cancelled'].includes(progress?.state || ''));
  const done = progress?.state === 'done';
  const terminalError = ['error','cancelled'].includes(progress?.state || '');
  const stage = progress?.state === 'cleanup' || done ? 4 : stages.findIndex(s => s.id === progress?.state);
  const percentage = done ? 100 : progress?.total ? Math.round(progress.current / progress.total * 90) : 0;
  const expired = !!ticket && now > ticket.expires_at * 1000;

  async function checkHealth() {
    try { setHealth(await (await request('/health', {signal:AbortSignal.timeout(8000)})).json()); setHealthError(''); }
    catch { setHealth(null); setHealthError('Backend belum terhubung. Jalankan backend atau periksa VITE_API_URL.'); }
  }
  useEffect(() => { void checkHealth(); const timer = setInterval(() => setNow(Date.now()), 15000); return () => clearInterval(timer); }, []);
  useEffect(() => {
    if (!ticket) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await (await request(`/jobs/${ticket!.id}`, {headers:{Authorization:`Bearer ${ticket!.token}`}, signal:AbortSignal.timeout(15000)})).json();
        if (stopped) return;
        setProgress(next); setError('');
        if (['done','error','cancelled'].includes(next.state)) return;
      } catch (e) {
        if (stopped) return;
        setError(e instanceof Error ? e.message : 'Koneksi terputus. Mencoba lagi…');
        if (Date.now() > ticket!.expires_at * 1000) return;
      }
      timer = setTimeout(poll, 1800);
    }
    void poll();
    return () => { stopped = true; clearTimeout(timer); };
  }, [ticket]);

  function credentialsChanged() { setProfiles([]); setProfile(''); }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (active) return;
    setBusy(true); setError('');
    const headers = {'Content-Type':'application/json', 'X-App-Key':accessKey};
    try {
      let selected = profile;
      if (health?.vpn_mode === 'portal' && !selected) {
        const result = await (await request('/vpn/profiles', {method:'POST', headers, body:JSON.stringify({username:sameAccount ? username : vpnUsername, password:sameAccount ? password : vpnPassword})})).json();
        if (!result.profiles.length) throw new Error('Tidak ada profil VPN yang tersedia.');
        if (result.profiles.length > 1) { setProfiles(result.profiles); setError('Pilih profil VPN di bawah, lalu lanjutkan.'); return; }
        selected = result.profiles[0].id;
      }
      const next = await (await request('/jobs', {method:'POST', headers, body:JSON.stringify({url,username,password,profile_id:selected,vpn_username:sameAccount ? username : vpnUsername,vpn_password:sameAccount ? password : vpnPassword})})).json();
      latestTicket.current = next; setTicket(next); setProgress(null); setPassword(''); setVpnPassword(''); setProfiles([]); setProfile('');
    } catch (e) { setError(e instanceof Error ? e.message : 'Tidak dapat memulai proses.'); }
    finally { setBusy(false); }
  }
  async function remove() {
    if (!ticket) return;
    try {
      await request(`/jobs/${ticket.id}`, {method:'DELETE',headers:{Authorization:`Bearer ${ticket.token}`}});
      setTicket(null); latestTicket.current = null; setProgress(null); setError('');
    } catch (e) { setError(e instanceof Error ? e.message : 'Gagal menghapus proses.'); }
  }
  async function save() {
    if (!ticket) return;
    setSaving(true);
    try {
      const response = await request(`/jobs/${ticket.id}/pdf`, {headers:{Authorization:`Bearer ${ticket.token}`}});
      const objectUrl = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a'); anchor.href = objectUrl; anchor.download = 'dokumen-unair.pdf'; anchor.click();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
    } catch (e) { setError(e instanceof Error ? e.message : 'Unduhan gagal.'); }
    finally { setSaving(false); }
  }

  return <div className="app-shell">
    <header><a href="/" className="brand"><span className="brand-mark"><BookOpen size={21}/></span>arsip<span className="brand-dot">.</span></a><span className="header-note">REPOSITORY TO PDF</span><a className="help-link" href="#cara-kerja"><CircleHelp size={16}/> Cara kerja</a></header>
    <main>
      <section className="intro"><div className="eyebrow"><span/> UNTUK RUANG BELAJAR ANDA</div><h1>Dari repository,<br/>ke ruang baca Anda<span>.</span></h1><p>Simpan dokumen UNAIR yang dapat Anda akses menjadi satu PDF. Semua halaman, tersusun dalam satu tempat. Tanpa instal aplikasi VPN — semua langsung dari browser.</p></section>
      <div className="workspace">
        <section className="form-card">
          <div className="card-heading"><div className="icon-tile"><FileText size={22}/></div><div><h2>Siapkan dokumen Anda</h2><p>Mulai dengan tautan dari repository.</p></div><span className="step-tag">01 — INPUT</span></div>
          <form onSubmit={submit}>
            <fieldset disabled={active}>
              <label htmlFor="url">Tautan dokumen <span>*</span></label>
              <div className="input-icon"><Link2 size={17}/><input id="url" type="url" placeholder="https://ir.unair.ac.id/opac/detail-opac?id=…" value={url} onChange={e => setUrl(e.target.value)} required maxLength={2048}/></div>
              <p className="field-help">Gunakan URL detail katalog atau halaman pembaca <code>index.html</code>.</p>
              <div className="divider"/>
              <div className="section-label"><KeyRound size={17}/><h3>Akun kampus</h3><span>SESI SEMENTARA</span></div>
              <div className="two-fields"><div><label htmlFor="username">NIM / username</label><input id="username" autoComplete="username" placeholder="Masukkan NIM Anda" value={username} onChange={e => {setUsername(e.target.value); credentialsChanged();}} required={health?.vpn_mode === 'portal'} maxLength={128}/></div><div><label htmlFor="password">Password</label><input id="password" type="password" autoComplete="current-password" placeholder="Password akun kampus" value={password} onChange={e => {setPassword(e.target.value); credentialsChanged();}} required={health?.vpn_mode === 'portal'} maxLength={256}/></div></div>
              {health?.vpn_mode === 'existing' && <p className="field-help">Boleh kosong jika URL pembaca dapat dibuka tanpa login tambahan.</p>}
              {health?.vpn_mode === 'portal' && <><label className="checkbox"><input type="checkbox" checked={sameAccount} onChange={e => {setSameAccount(e.target.checked); credentialsChanged();}}/> Gunakan akun yang sama untuk VPN</label>{!sameAccount && <div className="two-fields"><div><label htmlFor="vpn-user">Username VPN</label><input id="vpn-user" value={vpnUsername} onChange={e => {setVpnUsername(e.target.value); credentialsChanged();}} required/></div><div><label htmlFor="vpn-pass">Password VPN</label><input id="vpn-pass" type="password" value={vpnPassword} onChange={e => {setVpnPassword(e.target.value); credentialsChanged();}} required/></div></div>}</>}
              {profiles.length > 1 && <div className="extra-field"><label htmlFor="profile">Profil VPN</label><select id="profile" value={profile} onChange={e => setProfile(e.target.value)} required><option value="">Pilih profil kampus</option>{profiles.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></div>}
              {health?.access_key_required && <div className="extra-field"><label htmlFor="access">Kode akses aplikasi</label><input id="access" type="password" autoComplete="off" value={accessKey} onChange={e => setAccessKey(e.target.value)} placeholder="Kode dari pengelola aplikasi" required/></div>}
              <div className="privacy-note"><ShieldCheck size={18}/><p>Kredensial dikirim ke backend aplikasi untuk login resmi kampus. Aplikasi tidak menyimpannya di database atau browser. VPN diaktifkan otomatis oleh server.</p></div>
              <button className="primary" disabled={active || !health || health.status !== 'ok'} type="submit">{active ? <><LoaderCircle className="spin" size={18}/> Sedang memproses…</> : <>Buat PDF <ArrowRight size={18}/></>}</button>
            </fieldset>
            <p className="consent-note">Gunakan untuk dokumen yang berhak Anda akses dan simpan.</p>
          </form>
        </section>
        <aside className="output-card">
          <div className="output-top"><h2>Ruang unduhan</h2><span className="step-tag">02 — OUTPUT</span></div>
          {!ticket ? <div className="empty-state"><div className="paper-stack"><div className="paper back"/><div className="paper front"><FileText size={35}/><span/><span/><span/></div><span className="pdf-badge">PDF</span></div><h3>Satu dokumen. Siap dibaca.</h3><p>Progres dan hasil unduhan<br/>akan muncul di sini.</p><div className="empty-tags"><span><Check size={13}/> Urutan asli</span><span><Check size={13}/> Semua halaman tersedia</span></div></div> : <div className="job-panel" aria-live="polite">
            {done ? <><div className="success-icon"><CheckCircle2 size={32}/></div><h3>Dokumen siap.</h3><p className="document-title">{progress.result?.title}</p><div className="file-info"><FileText size={24}/><div><strong>dokumen-unair.pdf</strong><small>{progress.result?.pages} halaman · {((progress.result?.bytes || 0) / 1048576).toFixed(1)} MB</small></div><span>PDF</span></div><p className="field-help">PDF gambar, sesuai tampilan pembaca. Teks belum dapat diedit atau dicari.</p><button className="primary" onClick={save} disabled={saving || expired}>{saving ? <LoaderCircle className="spin" size={18}/> : <ArrowDownToLine size={18}/>} {expired ? 'Hasil kedaluwarsa' : 'Unduh PDF'}</button><p className="expiry">Tersedia sampai {new Date(ticket.expires_at * 1000).toLocaleTimeString('id-ID',{hour:'2-digit',minute:'2-digit'})}. Unduh sebelum menutup halaman.</p></> : <><div className={`progress-icon ${terminalError ? 'failed' : ''}`}>{terminalError ? <X size={26}/> : <LoaderCircle size={28} className="spin"/>}</div><h3>{terminalError ? 'Proses berhenti' : 'Menyiapkan bacaan Anda'}</h3><p className="progress-message">{progress?.message || 'Menghubungkan ke backend…'}</p><div className="progress-track"><span style={{width:`${percentage}%`}}/></div><div className="progress-caption"><span>{progress?.current || 0} / {progress?.total || '—'} halaman</span><strong>{percentage}%</strong></div><ol className="stages">{stages.map((s,i) => <li key={s.id} className={i < stage ? 'complete' : i === stage ? 'current' : ''}><span>{i < stage ? <Check size={13}/> : i+1}</span>{s.name}</li>)}</ol></>}
            {progress?.warning && <p className="warning">{progress.warning}</p>}
            <button className="text-button" onClick={remove}><Trash2 size={14}/>{done ? 'Hapus hasil dari server' : terminalError ? 'Tutup proses' : 'Batalkan proses'}</button>
          </div>}
          <div className="output-footer"><LockKeyhole size={15}/><span>Hasil privat · otomatis dihapus setelah {Math.round((health?.retention_seconds || 1800)/60)} menit</span></div>
        </aside>
      </div>
      {(error || healthError) && <div role="alert" className="error-banner"><CircleHelp size={18}/><span>{error || healthError}</span>{healthError && <button onClick={checkHealth}>Coba lagi</button>}</div>}
      <div className="connection-bar"><span className={`status-dot ${health ? 'online' : ''}`}/><span>{health ? health.vpn_mode === 'portal' ? 'All-in-one · VPN otomatis di server · tanpa instal aplikasi' : 'Mode lokal · menggunakan koneksi VPN laptop' : 'Menunggu backend'}</span><span className="connection-detail"><Wifi size={14}/> {health ? 'Backend terhubung' : 'Backend offline'}</span></div>
      <section id="cara-kerja" className="how"><div><span className="eyebrow">ALUR SEDERHANA</span><h2>Dari tautan menjadi arsip.</h2></div><div className="how-steps"><article><span>01</span><h3>Tempel tautan</h3><p>Ambil URL dokumen dari repository UNAIR.</p></article><article><span>02</span><h3>Isi akun kampus</h3><p>Server menghubungkan VPN dan membuka dokumen dengan akun Anda. Tanpa instal aplikasi apapun.</p></article><article><span>03</span><h3>Simpan PDF</h3><p>Halaman diperiksa, diurutkan, lalu disatukan untuk diunduh.</p></article></div></section>
      <details className="faq"><summary>Apakah ini mengunduh PDF asli? <ChevronDown size={16}/></summary><p>Aplikasi menyusun ulang halaman gambar yang disediakan pembaca repository. Hasil mengikuti resolusi sumber, bukan file PDF asli atau dokumen Word. Jika ada halaman yang tidak dapat diambil, proses berhenti dan tidak menyajikan PDF yang kurang lengkap. Aplikasi tidak membuka dokumen di luar hak akses akun.</p></details>
      <details className="faq"><summary>Apakah saya perlu instal VPN? <ChevronDown size={16}/></summary><p>Tidak. Server backend menangani koneksi VPN secara otomatis. Anda cukup memasukkan kredensial akun kampus di form, dan server akan menghubungkan VPN, mengakses dokumen, lalu menyusun PDF untuk Anda.</p></details>
    </main>
    <footer><span className="brand small">arsip.</span><span>Proyek independen · bukan layanan resmi Universitas Airlangga</span><span>Dibuat untuk membaca lebih nyaman.</span></footer>
  </div>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
