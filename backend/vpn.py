"""Official eduVPN manual-configuration flow; one isolated worker, one job at a time."""
import base64
import configparser
import logging
import ipaddress
import os
import platform
import re
import shutil
import socket
import subprocess
import tempfile
import time
import threading
import uuid
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .repository import Session, UserError, VPN, hidden_fields

logger = logging.getLogger(__name__)


def extract_wireguard_config(text: str) -> str:
    # 1. Inside data: URI (e.g. Apple mobileconfig base64 payload from eduVPN 3)
    for b64 in re.findall(r"data:[^;,]+;base64,([A-Za-z0-9+/=\s]+)", text):
        try:
            clean_b64 = re.sub(r"\s+", "", b64)
            decoded = base64.b64decode(clean_b64).decode("utf-8", errors="replace")
            wg_match = re.search(r"<key>WgQuickConfig</key>\s*<string>([\s\S]*?)</string>", decoded)
            if wg_match:
                candidate = wg_match.group(1).strip()
                if "[Interface]" in candidate and "[Peer]" in candidate:
                    return candidate
            if "[Interface]" in decoded and "[Peer]" in decoded:
                m2 = re.search(r"(\[Interface\][\s\S]*?\[Peer\][\s\S]*?)(?:</string>|\Z)", decoded)
                if m2:
                    candidate = m2.group(1).strip()
                    if "[Interface]" in candidate and "[Peer]" in candidate:
                        return candidate
        except Exception:
            continue

    # 2. Direct WireGuard config in text (cleanly bounded, avoiding HTML tag overflow)
    if "[Interface]" in text and "[Peer]" in text:
        match = re.search(r"(\[Interface\][\s\S]*?\[Peer\][\s\S]*?)(?:</(?:pre|code|string|textarea)>|<div|<p|<table|\Z)", text, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            candidate = re.split(r"</|<[a-zA-Z]", candidate)[0].strip()
            if "[Interface]" in candidate and "[Peer]" in candidate:
                return candidate

    # 3. Fallback: search any long base64 string
    for b64 in re.findall(r"([A-Za-z0-9+/=\s]{80,})", text):
        try:
            clean_b64 = re.sub(r"\s+", "", b64)
            decoded = base64.b64decode(clean_b64).decode("utf-8", errors="replace")
            wg_match = re.search(r"<key>WgQuickConfig</key>\s*<string>([\s\S]*?)</string>", decoded)
            if wg_match:
                candidate = wg_match.group(1).strip()
                if "[Interface]" in candidate and "[Peer]" in candidate:
                    return candidate
            if "[Interface]" in decoded and "[Peer]" in decoded:
                m2 = re.search(r"(\[Interface\][\s\S]*?\[Peer\][\s\S]*?)(?:</string>|\Z)", decoded)
                if m2:
                    candidate = m2.group(1).strip()
                    if "[Interface]" in candidate and "[Peer]" in candidate:
                        return candidate
        except Exception:
            continue

    raise UserError("Portal tidak memberikan konfigurasi WireGuard. Profil mungkin tidak mendukung protokol ini.")


class Portal:
    def __init__(self):
        self.session = Session("eduvpn.unair.ac.id")
        self.name = "arsip-" + uuid.uuid4().hex[:20]
        self.created = False

    def post(self, url, fields):
        return self.session.request("POST", url, data=fields,
                                    headers={
                                        "Referer": VPN,
                                        "Origin": "https://eduvpn.unair.ac.id",
                                        "Sec-Fetch-Dest": "document",
                                        "Sec-Fetch-Mode": "navigate",
                                        "Sec-Fetch-Site": "same-origin",
                                        "Sec-Fetch-User": "?1",
                                    })

    def login(self, username, password):
        soup, page = self.session.html(VPN)
        field = soup.select_one('input[name="userName"]')
        form = field.find_parent("form") if field else None
        if form is None:
            raise UserError("Metode login VPN berubah atau membutuhkan SSO/MFA; login otomatis belum dapat dilanjutkan.")
        fields = hidden_fields(form)
        fields.update(userName=username, userPass=password)
        self.post(urljoin(page, form.get("action", "")), fields)
        soup, page = self.session.html(VPN + "home")
        if soup.select_one('input[name="userPass"]'):
            raise UserError("Login VPN gagal. Periksa username dan password kampus.")
        form_select = soup.select_one('select[name="profileId"]')
        if not form_select:
            raise UserError("Portal tidak menyediakan konfigurasi manual untuk akun ini, atau kuota konfigurasi penuh. Hapus konfigurasi lama di portal eduVPN.")
        return [{"id": o.get("value", ""), "name": o.get_text(" ", strip=True)}
                for o in form_select.select("option[value]")]

    def create(self, profile_id):
        soup, page = self.session.html(VPN + "home")
        select = soup.select_one('select[name="profileId"]')
        if select is None or profile_id not in [x.get("value") for x in select.select("option")]:
            raise UserError("Profil VPN tidak tersedia untuk akun ini.")
        form = select.find_parent("form")
        fields = hidden_fields(form)
        fields.setdefault("action", "add_config")
        fields.update(profileId=profile_id, displayName=self.name, useProto="wireguard")
        # Cleanup also runs after an interrupted/failed response: creation may have succeeded.
        self.created = True
        target_action = form.get("action")
        target_url = urljoin(page, target_action) if target_action else page
        body, _, _ = self.post(target_url, fields)
        return extract_wireguard_config(body.decode("utf-8", errors="replace"))

    def _configuration_row(self, soup):
        for row in soup.select("tr"):
            if any(x.get("title") == self.name or x.get_text(strip=True) == self.name
                   for x in row.select("span, td")):
                return row
        return None

    @staticmethod
    def _delete_form(row):
        for form in row.select("form"):
            fields = hidden_fields(form)
            action = urlsplit(form.get("action", "")).path.rstrip("/")
            if fields.get("connectionId") and (fields.get("action") == "delete_config" or
                                                action.rsplit("/", 1)[-1] == "deleteConfig"):
                return form
        raise UserError("Formulir penghapusan konfigurasi VPN tidak ditemukan.")

    def close(self):
        warning = None
        try:
            if self.created:
                soup, page = self.session.html(VPN + "home")
                if soup.select_one('input[name="userPass"]'):
                    raise UserError("Sesi portal kedaluwarsa sebelum pembersihan.")
                row = self._configuration_row(soup)
                if row is not None:
                    form = self._delete_form(row)
                    target_url = urljoin(page, form.get("action") or "")
                    self.post(target_url, hidden_fields(form))
                    # Confirm removal even if the portal returns HTTP 200 on a failed POST.
                    confirmed, _ = self.session.html(VPN + "home")
                    if confirmed.select_one('input[name="userPass"]') or self._configuration_row(confirmed) is not None:
                        raise UserError("Portal belum mengonfirmasi penghapusan konfigurasi.")
                self.created = False
        except Exception as exc:
            logger.warning("VPN cleanup could not be confirmed (%s)", type(exc).__name__)
            warning = f"Pembersihan sesi VPN belum terkonfirmasi. Periksa konfigurasi {self.name} di portal eduVPN."
        try:
            self.post(VPN + "_logout", {})
        except Exception:
            pass
        finally:
            self.session.close()
        return warning


def sanitized_config(raw, repository_ips):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read_string(raw)
        interface, peer = parser["Interface"], parser["Peer"]
        allowed = [ipaddress.ip_network(x.strip(), strict=False) for x in peer["AllowedIPs"].split(",")]
        for ip in repository_ips:
            if not any(ipaddress.ip_address(ip) in network for network in allowed):
                raise UserError("Profil VPN ini tidak memberi rute ke repository UNAIR.")
        key = interface["PrivateKey"].strip()
        pubkey = peer["PublicKey"].strip()
        if not all(re.fullmatch(r"[A-Za-z0-9+/]{43}=", k) for k in (key, pubkey)):
            raise ValueError("invalid wireguard key")
        psk = peer.get("PresharedKey", "").strip()
        if psk and not re.fullmatch(r"[A-Za-z0-9+/]{43}=", psk):
            raise ValueError("invalid preshared key")
        psk_line = f"PresharedKey = {psk}\n" if psk else ""
        addresses = [str(ipaddress.ip_interface(x.strip())) for x in interface["Address"].split(",")
                     if ipaddress.ip_interface(x.strip()).version == 4]
        if not addresses:
            raise ValueError("address")
        endpoint = peer["Endpoint"].strip()
        if not re.fullmatch(r"[A-Za-z0-9.-]+:\d{1,5}", endpoint):
            raise ValueError(f"invalid endpoint: {endpoint!r}")
        # Rebuild from validated fields: no hooks, shell commands, default routes, or DNS changes.
        return (f"[Interface]\nPrivateKey = {key}\nAddress = {','.join(addresses)}\nTable = off\n"
                f"[Peer]\nPublicKey = {pubkey}\n{psk_line}AllowedIPs = {','.join(ip + '/32' for ip in repository_ips)}\n"
                f"Endpoint = {endpoint}\nPersistentKeepalive = 25\n")
    except (KeyError, ValueError, configparser.Error):
        raise UserError("Konfigurasi WireGuard dari portal tidak valid; periksa profil VPN.") from None


def wireproxy_config(raw, bind_port=1080):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read_string(raw)
        interface, peer = parser["Interface"], parser["Peer"]
        key = interface["PrivateKey"].strip()
        pubkey = peer["PublicKey"].strip()
        if not all(len(base64.b64decode(k, validate=True)) == 32 for k in (key, pubkey)):
            raise ValueError("invalid wireguard key")
        psk = peer.get("PresharedKey", "").strip() or peer.get("PreSharedKey", "").strip()
        if psk and len(base64.b64decode(psk, validate=True)) != 32:
            raise ValueError("invalid preshared key")
        psk_line = f"PreSharedKey = {psk}\n" if psk else ""
        addresses = [str(ipaddress.ip_interface(x.strip())) for x in interface["Address"].split(",")]
        if not addresses:
            raise ValueError("address")
        endpoint = peer["Endpoint"].strip()
        host, port = endpoint.rsplit(":", 1)
        if not 1 <= int(port) <= 65535:
            raise ValueError("endpoint port")
        if host.startswith("[") and host.endswith("]"):
            ipaddress.IPv6Address(host[1:-1])
        elif not re.fullmatch(r"[A-Za-z0-9.-]+", host):
            raise ValueError("endpoint host")
        dns_ips = []
        for x in interface.get("DNS", "1.1.1.1").split(","):
            x = x.strip()
            try:
                ipaddress.ip_address(x)
                dns_ips.append(x)
            except ValueError:
                pass
        dns = ", ".join(dns_ips) if dns_ips else "1.1.1.1"
        allowed = [str(ipaddress.ip_network(x.strip(), strict=False))
                   for x in peer.get("AllowedIPs", "0.0.0.0/0,::/0").split(",")]
        mtu = int(interface.get("MTU", "1420"))
        if not 1280 <= mtu <= 9000 or not 1 <= bind_port <= 65535:
            raise ValueError("MTU or proxy port")
        return (f"[Interface]\nPrivateKey = {key}\nAddress = {','.join(addresses)}\nDNS = {dns}\nMTU = {mtu}\n\n"
                f"[Peer]\nPublicKey = {pubkey}\n{psk_line}Endpoint = {endpoint}\nAllowedIPs = {','.join(allowed)}\n"
                f"PersistentKeepalive = 25\n\n"
                f"[Socks5]\nBindAddress = 127.0.0.1:{bind_port}\n")
    except (KeyError, ValueError, configparser.Error):
        raise UserError("Konfigurasi WireGuard dari portal tidak valid; periksa alamat, key, endpoint, dan profil VPN.") from None


def ensure_wireproxy():
    explicit = os.getenv("WIREPROXY_BIN")
    if explicit:
        path = Path(explicit)
        return str(path.resolve()) if path.is_file() else None
    cmd = shutil.which("wireproxy")
    if cmd:
        return cmd
    return None


def safe_wireproxy_output(output):
    # Wireproxy receives VPN keys, never the user's login credentials. Remove both
    # WireGuard encodings plus whole key/password field values before logging stderr.
    output = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output)
    output = re.sub(r"(?im)(\b(?:private[_ ]?key|preshared[_ ]?key|public[_ ]?key|password|userpass)\s*[:=]).*$", r"\1 [REDACTED]", output)
    output = re.sub(r"(?im)((?:invalid (?:base64 string|key)|key should be \d+ bytes)\s*:).*$", r"\1 [REDACTED]", output)
    output = re.sub(r"[A-Za-z0-9+/]{43}=", "[REDACTED]", output)
    output = re.sub(r"(?i)\b[0-9a-f]{64}\b", "[REDACTED]", output)
    output = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", output)
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    # Keep the fatal tail rather than thousands of WireGuard debug messages.
    return " | ".join(lines[-4:])[:1600] or "Proses tidak menulis detail ke stderr."


def wireproxy_failure(output, stage, code=None):
    lower = output.lower()
    reason = "Periksa profil VPN dan versi binary Wireproxy pada backend."
    if "no such file or directory" in lower and ("landlock" in lower or "rule" in lower or "/dev/" in lower or "/proc/" in lower or "/etc/" in lower or "/usr/share/" in lower):
        reason = "Wireproxy gagal menerapkan aturan filesystem Linux. Rebuild backend dengan binary terbaru yang disertakan proyek."
    elif "landlock" in lower:
        reason = "Aturan Landlock Wireproxy gagal diterapkan pada container. Periksa detail runtime dan versi image."
    elif "address already in use" in lower or "only one usage" in lower:
        reason = "Port proxy sedang dipakai; coba ulang proses."
    elif "no such host" in lower or "name resolution" in lower or "lookup " in lower:
        reason = "DNS backend gagal menemukan endpoint VPN."
    elif "parseaddr" in lower or "parseprefix" in lower or "invalid ip" in lower:
        reason = "Alamat IP atau DNS konfigurasi VPN tidak didukung."
    elif "invalid key" in lower or "key should" in lower or "base64" in lower:
        reason = "Key WireGuard dari portal tidak valid."
    elif "permission denied" in lower or "operation not permitted" in lower:
        reason = "Platform backend menolak menjalankan Wireproxy atau membuka socket UDP."
    elif "cannot allocate memory" in lower or "out of memory" in lower or "newosproc" in lower:
        reason = "Resource memori atau thread backend tidak mencukupi."
    label = f"Wireproxy gagal saat {stage} (exit {code}). {reason}"
    diagnostic = safe_wireproxy_output(output)
    logger.error("%s Detail: %s", label, diagnostic)
    return UserError(f"{label} Detail: {diagnostic}")


class Tunnel:
    def __init__(self):
        self.directory = None
        self.path = None
        self.proc = None
        self.proxy_url = None
        self.wireproxy_bin = ensure_wireproxy()
        self.mode = "wireproxy"
        self.started = False
        self.output = deque(maxlen=32)
        self.reader = None

    def _read_output(self):
        # Continuously drain the pipe so long downloads cannot deadlock Wireproxy.
        try:
            while chunk := self.proc.stdout.read(1024):
                self.output.append(chunk)
        except (OSError, ValueError):
            pass

    def _startup_error(self, stage):
        if self.reader:
            self.reader.join(timeout=1)
        return wireproxy_failure("".join(self.output), stage, self.proc.returncode)

    @staticmethod
    def command(args):
        result = subprocess.run(args, capture_output=True, timeout=30, check=False)
        if result.returncode:
            # wg-quick output can contain key/configuration data: never relay to HTTP/logs.
            raise UserError("VPN server gagal diaktifkan. Periksa WireGuard, izin NET_ADMIN, dan dukungan kernel pada backend.")

    def start(self, config):
        if self.mode == "wireproxy":
            if not self.wireproxy_bin:
                raise UserError("Binary Wireproxy tidak tersedia. Rebuild image backend atau atur WIREPROXY_BIN.")
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            content = wireproxy_config(config, bind_port=port)
            self.directory = tempfile.TemporaryDirectory(prefix="arsip-wp-")
            self.path = Path(self.directory.name) / "wireproxy.conf"
            self.path.write_text(content, encoding="utf-8")
            self.path.chmod(0o600)
            try:
                check = subprocess.run([self.wireproxy_bin, "-n", "-c", str(self.path)],
                                       capture_output=True, text=True, timeout=20)
                if check.returncode:
                    raise wireproxy_failure(check.stderr + check.stdout, "validasi konfigurasi", check.returncode)
                self.proc = subprocess.Popen([self.wireproxy_bin, "-c", str(self.path)],
                                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                             text=True, encoding="utf-8", errors="replace")
                self.reader = threading.Thread(target=self._read_output, daemon=True)
                self.reader.start()
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if self.proc.poll() is not None:
                        raise self._startup_error("startup")
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=0.3) as connection:
                            connection.sendall(b"\x05\x01\x00")
                            reply = b""
                            while len(reply) < 2:
                                chunk = connection.recv(2 - len(reply))
                                if not chunk:
                                    break
                                reply += chunk
                            if reply == b"\x05\x00" and self.proc.poll() is None:
                                break
                    except OSError:
                        pass
                    time.sleep(0.1)
                else:
                    raise UserError("Wireproxy timeout saat menyiapkan SOCKS5. Periksa resource backend.")
            except subprocess.TimeoutExpired:
                raise UserError("Validasi Wireproxy timeout. Periksa DNS endpoint VPN pada backend.") from None
            except OSError as exc:
                raise wireproxy_failure(str(exc), "eksekusi binary", exc.errno) from None
            self.started = True
            self.proxy_url = f"socks5://127.0.0.1:{port}"
            return self.proxy_url

        if platform.system() != "Linux" or os.geteuid() != 0:
            raise UserError("VPN otomatis memerlukan wireproxy atau Linux dengan NET_ADMIN. Untuk Windows gunakan mode VPN yang sudah terhubung.")
        ips = sorted({item[4][0] for item in socket.getaddrinfo("ir.unair.ac.id", 443, socket.AF_INET)})
        if not ips:
            raise UserError("Alamat repository tidak dapat ditemukan.")
        content = sanitized_config(config, ips)
        self.directory = tempfile.TemporaryDirectory(prefix="arsip-vpn-", dir="/run")
        self.path = Path(self.directory.name) / "arsipwg.conf"
        self.path.write_text(content, encoding="utf-8")
        self.path.chmod(0o600)
        self.started = True
        self.command(["wg-quick", "up", str(self.path)])
        for ip in ips:
            # 'add', not 'replace': never overwrite an existing host route.
            self.command(["ip", "route", "add", ip + "/32", "dev", "arsipwg"])
        time.sleep(1)
        self.proxy_url = None
        return None

    def close(self):
        success = True
        try:
            if self.mode == "wireproxy":
                if self.proc:
                    if self.proc.poll() is None:
                        self.proc.terminate()
                    try:
                        self.proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.proc.kill()
                        self.proc.wait(timeout=5)
                    if self.reader:
                        self.reader.join(timeout=2)
                    if self.proc.stdout:
                        self.proc.stdout.close()
                    self.proc = None
            else:
                if self.started and self.path:
                    self.command(["wg-quick", "down", str(self.path)])
        except Exception:
            success = False
        finally:
            if self.directory:
                try:
                    self.directory.cleanup()
                    self.directory = None
                except OSError:
                    success = False
            self.output.clear()
            self.started = False
            self.proxy_url = None
        return success
