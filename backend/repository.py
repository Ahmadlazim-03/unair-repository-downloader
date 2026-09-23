"""Bounded, TLS-verified access to one repository. Never execute remote JavaScript."""
import io
import re
import ssl
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit, unquote

import httpx
import pymupdf
from bs4 import BeautifulSoup
from PIL import Image

REPO = "https://ir.unair.ac.id"
VPN = "https://eduvpn.unair.ac.id/vpn-user-portal/"


class UserError(Exception):
    pass


def safe_url(url: str, host: str = "ir.unair.ac.id") -> str:
    p = urlsplit(url)
    if (p.scheme != "https" or p.hostname != host or p.port not in (None, 443)
            or p.username or p.password or p.fragment or "\\" in url
            or any(ord(c) < 32 for c in url)):
        raise UserError("URL harus HTTPS pada domain resmi yang didukung.")
    return url


def input_url(url: str) -> str:
    safe_url(url)
    p = urlsplit(url)
    if not (p.path == "/opac/detail-opac" or
            (p.path.startswith("/uploaded_files/") and p.path.endswith("/index.html"))):
        raise UserError("Masukkan URL detail katalog atau index.html pembaca UNAIR.")
    if any(x == ".." for x in unquote(p.path).split("/")):
        raise UserError("Path URL tidak valid.")
    return url


def hidden_fields(form) -> dict:
    return {i["name"]: i.get("value", "") for i in form.select('input[type=hidden][name]')}


class Session:
    def __init__(self, host="ir.unair.ac.id", transport=None, proxy=None):
        self.host = host
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "id,en-US;q=0.9,en;q=0.8",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }
        self.client = httpx.Client(verify=ssl.create_default_context(), timeout=30,
                                  follow_redirects=False, transport=transport, proxy=proxy,
                                  headers=headers)

    def close(self):
        self.client.close()

    def request(self, method, url, *, data=None, headers=None, limit=6_000_000):
        req_headers = dict(headers or {})
        for _ in range(6):
            safe_url(url, self.host)
            with self.client.stream(method, url, data=data, headers=req_headers) as r:
                if r.is_redirect:
                    target = urljoin(url, r.headers.get("location", ""))
                    safe_url(target, self.host)  # validate BEFORE forwarding cookies or form data
                    if r.status_code == 303 or (r.status_code in (301, 302) and method == "POST"):
                        method, data = "GET", None
                        req_headers.pop("Origin", None)
                    url = target
                    continue
                if r.status_code in (401, 403):
                    raise UserError("Akses ditolak oleh kampus. Periksa akun dan hak akses dokumen.")
                if r.status_code >= 400:
                    raise UserError(f"Repository mengembalikan HTTP {r.status_code}; proses dihentikan.")
                chunks, size = [], 0
                for chunk in r.iter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise UserError("Ukuran respons melewati batas keamanan aplikasi.")
                    chunks.append(chunk)
                return b"".join(chunks), url, r.headers
        raise UserError("Terlalu banyak pengalihan halaman.")

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def html(self, url):
        body, final, _ = self.get(url)
        return BeautifulSoup(body, "html.parser"), final


def viewer_links(soup, base):
    candidates = []
    for element in soup.select("a[href], iframe[src]"):
        value = element.get("href") or element.get("src", "")
        if "uploaded_files/" in value and "index.html" in value:
            candidates.append(urljoin(base, value))
    # Some INLISLite versions keep the viewer URL in onclick/window.open.
    for value in re.findall(r'''["']([^"'<>]*uploaded_files/[^"'<>]*?/index\.html(?:\?[^"'<>]*)?)["']''', str(soup)):
        candidates.append(urljoin(base, value.replace("\\/", "/")))
    return list(dict.fromkeys(safe_url(x) for x in candidates))


def resolve_viewer(session, url, username, password):
    input_url(url)
    soup, final = session.html(url)
    title = soup.title.get_text(" ", strip=True) if soup.title else "Dokumen repository UNAIR"
    if "/uploaded_files/" in final:
        return final, title
    links = viewer_links(soup, final)
    if not links:
        if not username or not password:
            raise UserError("Detail katalog memerlukan login. Isi NIM dan password repository.")
        csrf = soup.select_one('meta[name="csrf-token"]')
        headers = {"X-CSRF-Token": csrf.get("content", "")} if csrf else {}
        body, _, _ = session.request("POST", REPO + "/opac/site/login", headers=headers)
        form = BeautifulSoup(body, "html.parser").select_one("form#login-anggota")
        if form is None:
            raise UserError("Form login repository berubah atau VPN belum terhubung.")
        fields = hidden_fields(form)
        fields.update({"LoginKeanggotaanForm[noanggota]": username,
                       "LoginKeanggotaanForm[password]": password})
        session.request("POST", REPO + "/opac/site/loginanggota", data=fields, headers=headers)
        soup, final = session.html(url)
        links = viewer_links(soup, final)
        if not links:
            raise UserError("Login belum membuka tautan Baca Online. Periksa kredensial; jika perlu gunakan URL pembaca setelah login resmi.")
    if len(links) > 1:
        raise UserError("Katalog berisi beberapa dokumen. Buka dokumen yang diinginkan lalu masukkan URL index.html pembacanya.")
    return links[0], title


def parse_config(source: str, maximum: int):
    # Last assignment is the active FlipHTML5 configuration.
    counts = re.findall(r'bookConfig\.totalPageCount\s*=\s*["\']?(\d+)', source)
    if not counts:
        raise UserError("Pembaca ini belum didukung: jumlah halaman tidak ditemukan.")
    count = int(counts[-1])
    if not 1 <= count <= maximum:
        raise UserError(f"Jumlah halaman di luar batas 1–{maximum} halaman.")
    paths = re.findall(r'''bookConfig\.normalPath\s*=\s*["']([^"']+)["']''', source)
    path = paths[-1] if paths else "files/mobile/"
    if not re.fullmatch(r"files/[A-Za-z0-9_/-]+/", path) or ".." in path:
        raise UserError("Lokasi gambar pembaca tidak didukung.")
    return count, path


def build_pdf(session, viewer, title, destination: Path, update, cancelled,
              maximum=500, max_bytes=250_000_000):
    base = urljoin(viewer, "./")
    config, _, _ = session.get(urljoin(base, "mobile/javascript/config.js"))
    count, normal = parse_config(config.decode("utf-8", errors="replace"), maximum)
    total = 0
    doc = pymupdf.open()
    try:
        for index in range(1, count + 1):
            if cancelled():
                raise UserError("Proses dibatalkan.")
            body = None
            for attempt in range(3):
                try:
                    body, _, _ = session.get(urljoin(base, f"{normal}{index}.jpg"), limit=12_000_000)
                    break
                except httpx.TransportError:
                    if attempt == 2:
                        raise
                    time.sleep(0.5 * (attempt + 1))
            total += len(body)
            if total > max_bytes:
                raise UserError("Total dokumen melebihi batas ukuran aplikasi.")
            try:
                with Image.open(io.BytesIO(body)) as picture:
                    width, height = picture.size
                    if width * height > 30_000_000 or min(width, height) < 50:
                        raise ValueError("dimensions")
                    picture.verify()
            except Exception:
                raise UserError(f"Halaman {index} bukan gambar valid. PDF tidak diterbitkan agar tidak kehilangan halaman.") from None
            page = doc.new_page(width=595.276, height=595.276 * height / width)
            page.insert_image(page.rect, stream=body)
            update("download", f"Mengambil halaman {index} dari {count}", index, count)
        update("assemble", "Memeriksa dan menyusun PDF lengkap", count, count)
        doc.set_metadata({"title": title[:500], "creator": "Arsip Repository", "subject": viewer})
        doc.save(str(destination), garbage=4, deflate=True)
    finally:
        doc.close()
    with pymupdf.open(destination) as check:
        if len(check) != count or any(not page.get_images() for page in check):
            destination.unlink(missing_ok=True)
            raise UserError("Verifikasi PDF gagal.")
    return {"pages": count, "bytes": destination.stat().st_size, "title": title,
            "format": "PDF gambar", "text_searchable": False}
