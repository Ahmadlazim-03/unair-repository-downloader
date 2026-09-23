import asyncio
import hmac
import os
import secrets
import shutil
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, SecretStr
from starlette.background import BackgroundTask

from .repository import Session, UserError, build_pdf, input_url, resolve_viewer
from .vpn import Portal, Tunnel, ensure_wireproxy

MODE = os.getenv("VPN_MODE", "existing")
ACCESS_KEY = os.getenv("APP_ACCESS_KEY", "")
ORIGINS = [s.strip() for s in os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(",") if s.strip()]
TTL = max(120, int(os.getenv("JOB_TTL_SECONDS", "1800")))
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "")
jobs = {}
lock = threading.Lock()
network_lock = threading.Lock()
network_healthy = True


@dataclass
class Job:
    token: str
    directory: tempfile.TemporaryDirectory
    created: float = field(default_factory=time.time)
    state: str = "queued"
    message: str = "Menyiapkan proses"
    current: int = 0
    total: int = 0
    result: dict | None = None
    warning: str | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    finished: bool = False
    downloading: int = 0

    @property
    def pdf(self):
        return Path(self.directory.name) / "dokumen-unair.pdf"

    def update(self, state, message, current=0, total=0):
        with lock:
            self.state, self.message, self.current, self.total = state, message, current, total


def reap():
    with lock:
        for key, job in list(jobs.items()):
            if time.time() - job.created > TTL:
                job.cancel.set()
                if job.finished and not job.downloading:
                    job.directory.cleanup()
                    jobs.pop(key, None)


@asynccontextmanager
async def lifespan(app):
    if MODE not in ("existing", "portal"):
        raise RuntimeError("VPN_MODE must be existing or portal")
    if MODE == "portal" and ACCESS_KEY and len(ACCESS_KEY) < 8:
        raise RuntimeError("APP_ACCESS_KEY minimal 8 karakter")
    async def cleanup_loop():
        while True:
            reap()
            await asyncio.sleep(15)
    task = asyncio.create_task(cleanup_loop())
    yield
    task.cancel()
    for job in list(jobs.values()):
        job.cancel.set()


app = FastAPI(title="Arsip Repository Worker", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS,
                   allow_methods=["GET", "POST", "DELETE"],
                   allow_headers=["Content-Type", "Authorization", "X-App-Key"],
                   expose_headers=["Content-Disposition"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    # CORS alone doesn't block writes. Reject foreign origins before processing.
    if request.headers.get("origin") and ("*" not in ORIGINS and request.headers["origin"] not in ORIGINS):
        return JSONResponse({"detail": "Origin tidak diizinkan."}, status_code=403)
    if request.method == "POST":
        try:
            if int(request.headers.get("content-length", "0")) > 16_384:
                return JSONResponse({"detail": "Permintaan terlalu besar."}, status_code=413)
            # Bound chunked requests too; Starlette caches the body for downstream use.
            size, chunks = 0, []
            async for chunk in request.stream():
                size += len(chunk)
                if size > 16_384:
                    return JSONResponse({"detail": "Permintaan terlalu besar."}, status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        except ValueError:
            return JSONResponse({"detail": "Header tidak valid."}, status_code=400)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Pydantic errors can contain the submitted credential. Do not return input values.
    return JSONResponse({"detail": "Input tidak valid. Periksa URL dan kolom yang diperlukan."}, status_code=422)


@app.exception_handler(UserError)
async def user_error(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


def gate(request: Request, x_app_key: str = Header(default="")):
    if ACCESS_KEY:
        if not hmac.compare_digest(x_app_key, ACCESS_KEY):
            raise HTTPException(401, "Kode akses aplikasi tidak sesuai.")
    elif os.getenv("ALLOW_PUBLIC_WITHOUT_KEY", "").lower() != "true" and request.client and request.client.host not in ("127.0.0.1", "::1", "testclient"):
        raise HTTPException(403, "Backend tanpa kode akses hanya menerima localhost. Atur APP_ACCESS_KEY di environment.")


class Credentials(BaseModel):
    username: str = Field(default="", max_length=128)
    password: SecretStr = Field(default=SecretStr(""), max_length=256)


class Submission(Credentials):
    url: str = Field(max_length=2048)
    vpn_username: str = Field(default="", max_length=128)
    vpn_password: SecretStr = Field(default=SecretStr(""), max_length=256)
    profile_id: str = Field(default="", max_length=128)


@app.get("/health")
def health():
    binary_available = bool(ensure_wireproxy()) if MODE == "portal" else None
    state = "restart_required" if not network_healthy else "vpn_unavailable" if binary_available is False else "ok"
    message = ("Backend perlu direstart karena tunnel sebelumnya belum bersih." if state == "restart_required" else
               "Binary Wireproxy tidak tersedia. Rebuild image backend." if state == "vpn_unavailable" else "")
    return {"status": state, "vpn_mode": MODE, "vpn_engine": "wireproxy" if MODE == "portal" else "existing",
            "message": message,
            "wireproxy_available": binary_available,
            "access_key_required": bool(ACCESS_KEY), "retention_seconds": TTL}


@app.post("/vpn/profiles", dependencies=[Depends(gate)])
def profiles(data: Credentials):
    if MODE != "portal":
        return {"profiles": []}
    if not data.username or not data.password.get_secret_value():
        raise UserError("Isi kredensial VPN terlebih dahulu.")
    if not network_lock.acquire(blocking=False):
        raise HTTPException(409, "Backend sedang digunakan. Coba setelah proses selesai.")
    portal = None
    try:
        portal = Portal()
        return {"profiles": portal.login(data.username, data.password.get_secret_value())}
    except httpx.HTTPError:
        raise UserError("Portal VPN tidak dapat dihubungi dengan koneksi TLS yang valid.") from None
    finally:
        data.password = SecretStr("")
        if portal:
            portal.close()
        network_lock.release()


def run(job, data):
    global network_healthy
    portal, tunnel, session, proxy_url = None, None, None, None
    try:
        if MODE == "portal":
            tunnel = Tunnel()
            job.update("vpn", "Login dan menghubungkan VPN kampus")
            portal = Portal()
            available = portal.login(data.vpn_username or data.username,
                                     data.vpn_password.get_secret_value() or data.password.get_secret_value())
            chosen = data.profile_id
            if not chosen and len(available) == 1:
                chosen = available[0]["id"]
            if chosen not in [p["id"] for p in available]:
                raise UserError("Pilih profil VPN yang akan digunakan.")
            proxy_url = tunnel.start(portal.create(chosen))
        if job.cancel.is_set():
            raise UserError("Proses dibatalkan.")
        job.update("auth", "Memeriksa akses dokumen di repository")
        session = Session(proxy=proxy_url)
        viewer, title = resolve_viewer(session, data.url, data.username, data.password.get_secret_value())
        data.password = SecretStr("")
        data.vpn_password = SecretStr("")
        job.result = build_pdf(session, viewer, title, job.pdf, job.update, job.cancel.is_set,
                               int(os.getenv("MAX_PAGES", "500")), int(os.getenv("MAX_TOTAL_MB", "250")) * 1_000_000)
        if job.cancel.is_set():
            raise UserError("Proses dibatalkan.")
        job.update("cleanup", "Menutup koneksi dan membersihkan sesi")
    except UserError as exc:
        job.update("cancelled" if job.cancel.is_set() else "error", str(exc))
    except httpx.HTTPError:
        job.update("error", "Koneksi repository melalui VPN gagal. Periksa DNS, akses UDP keluar ke endpoint VPN, dan TLS backend." if proxy_url else
                   "Koneksi repository gagal. Periksa VPN, jaringan, dan sertifikat TLS backend.")
    except Exception:
        job.update("error", "Proses gagal. Periksa konfigurasi backend dan format dokumen; tidak ada PDF parsial yang diterbitkan.")
    finally:
        data.password = SecretStr("")
        data.vpn_password = SecretStr("")
        if session:
            session.close()
        if tunnel and not tunnel.close():
            network_healthy = False
            job.warning = "Pembersihan tunnel gagal; backend harus direstart sebelum proses berikutnya."
        if portal:
            warning = portal.close()
            if warning:
                job.warning = warning
        with lock:
            if job.state == "cleanup":
                job.state, job.message = "done", "PDF lengkap siap diunduh"
                if OUTPUT_DIR and Path(OUTPUT_DIR).is_dir() and job.pdf.is_file():
                    try:
                        title = (job.result or {}).get("title", "")
                        clean = "".join(c for c in title if c.isalnum() or c in " ._-").strip() or "dokumen-unair"
                        # ponytail: direct copy, add collision numbering if overwriting is unwanted
                        shutil.copy2(job.pdf, Path(OUTPUT_DIR) / f"{clean}.pdf")
                    except Exception:
                        pass
            else:
                job.pdf.unlink(missing_ok=True)
            job.finished = True
        network_lock.release()


@app.post("/jobs", status_code=202, dependencies=[Depends(gate)])
def create_job(data: Submission):
    input_url(data.url)
    reap()
    if not network_healthy:
        raise HTTPException(503, "Backend perlu direstart karena tunnel sebelumnya belum bersih.")
    with lock:
        if len(jobs) >= 8:
            raise HTTPException(429, "Penyimpanan sementara penuh. Hapus hasil lama atau coba lagi nanti.")
    if not network_lock.acquire(blocking=False):
        raise HTTPException(409, "Satu dokumen sedang diproses. Coba lagi setelah selesai.")
    job = None
    job_id = secrets.token_urlsafe(18)
    token = secrets.token_urlsafe(32)
    try:
        job = Job(token=token, directory=tempfile.TemporaryDirectory(prefix="arsip-job-"))
        with lock:
            jobs[job_id] = job
        threading.Thread(target=run, args=(job, data), daemon=True).start()
    except Exception:
        with lock:
            jobs.pop(job_id, None)
        if job:
            job.directory.cleanup()
        network_lock.release()
        raise HTTPException(503, "Backend tidak dapat menyiapkan proses. Coba lagi nanti.") from None
    return {"id": job_id, "token": token, "expires_at": job.created + TTL}


def authorize(job_id, authorization):
    with lock:
        job = jobs.get(job_id)
        if not job or not hmac.compare_digest(authorization, "Bearer " + job.token):
            raise HTTPException(404, "Proses tidak ditemukan atau token tidak sesuai.")
        if time.time() - job.created > TTL:
            job.cancel.set()
            raise HTTPException(410, "Hasil sudah kedaluwarsa. Buat proses baru.")
        return job


@app.get("/jobs/{job_id}")
def status(job_id: str, authorization: str = Header(default="")):
    job = authorize(job_id, authorization)
    with lock:
        return {"state": job.state, "message": job.message, "current": job.current,
                "total": job.total, "result": job.result if job.state == "done" else None,
                "warning": job.warning, "expires_at": job.created + TTL}


@app.get("/jobs/{job_id}/pdf")
def download(job_id: str, authorization: str = Header(default="")):
    job = authorize(job_id, authorization)
    with lock:
        if job.state != "done" or not job.pdf.is_file():
            raise HTTPException(409, "PDF belum siap.")
        job.downloading += 1
    def finished():
        with lock:
            job.downloading -= 1
    return FileResponse(job.pdf, media_type="application/pdf", filename="dokumen-unair.pdf",
                        background=BackgroundTask(finished))


@app.delete("/jobs/{job_id}", status_code=202)
def cancel(job_id: str, authorization: str = Header(default="")):
    job = authorize(job_id, authorization)
    job.cancel.set()
    with lock:
        if job.finished and not job.downloading:
            job.directory.cleanup()
            jobs.pop(job_id, None)
    return {"message": "Proses dibatalkan atau hasil telah dihapus."}
