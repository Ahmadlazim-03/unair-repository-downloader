"""Official eduVPN manual-configuration flow; one isolated worker, one job at a time."""
import base64
import configparser
import ipaddress
import os
import platform
import re
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .repository import Session, UserError, VPN, hidden_fields


def extract_wireguard_config(text: str) -> str:
    # 1. Direct WireGuard config in text
    if "[Interface]" in text and "[Peer]" in text:
        match = re.search(r"(\[Interface\][\s\S]*?\[Peer\][\s\S]*?)(?:</string>|\Z)", text)
        if match:
            return match.group(1).strip()

    # 2. Inside data: URI (e.g. Apple mobileconfig base64 payload from eduVPN 3)
    for b64 in re.findall(r"data:application/[^;]+;base64,([A-Za-z0-9+/=]+)", text):
        try:
            decoded = base64.b64decode(b64).decode("utf-8", errors="replace")
            wg_match = re.search(r"<key>WgQuickConfig</key>\s*<string>([\s\S]*?)</string>", decoded)
            if wg_match:
                return wg_match.group(1).strip()
            if "[Interface]" in decoded and "[Peer]" in decoded:
                m2 = re.search(r"(\[Interface\][\s\S]*?\[Peer\][\s\S]*?)(?:</string>|\Z)", decoded)
                if m2:
                    return m2.group(1).strip()
        except Exception:
            continue

    # 3. Fallback: search any long base64 string
    for b64 in re.findall(r"([A-Za-z0-9+/]{80,}={0,2})", text):
        try:
            decoded = base64.b64decode(b64).decode("utf-8", errors="replace")
            if "[Interface]" in decoded and "[Peer]" in decoded:
                wg_match = re.search(r"<key>WgQuickConfig</key>\s*<string>([\s\S]*?)</string>", decoded)
                if wg_match:
                    return wg_match.group(1).strip()
                m2 = re.search(r"(\[Interface\][\s\S]*?\[Peer\][\s\S]*?)(?:</string>|\Z)", decoded)
                if m2:
                    return m2.group(1).strip()
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
        soup, _ = self.session.html(VPN + "home")
        if soup.select_one('input[name="userPass"]'):
            raise UserError("Login VPN gagal. Periksa username dan password kampus.")
        form = soup.select_one('select[name="profileId"]')
        if not form:
            raise UserError("Portal tidak menyediakan konfigurasi manual untuk akun ini, atau kuota konfigurasi penuh. Diperlukan bantuan pengelola VPN kampus.")
        return [{"id": o.get("value", ""), "name": o.get_text(" ", strip=True)}
                for o in form.select("option[value]")]

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

    def close(self):
        warning = None
        try:
            if self.created:
                soup, page = self.session.html(VPN + "home")
                if soup.select_one('input[name="userPass"]'):
                    raise UserError("session expired")
                for row in soup.select("tr"):
                    # Exact generated label only; never delete another client's configuration.
                    if not any(x.get("title") == self.name or x.get_text(strip=True) == self.name or self.name in x.get_text()
                               for x in row.select("span, td")):
                        continue
                    form = row.select_one("form")
                    if form:
                        target_action = form.get("action")
                        target_url = urljoin(page, target_action) if target_action else page
                        self.post(target_url, hidden_fields(form))
                        break
            self.post(VPN + "_logout", {})
        except Exception:
            warning = f"Pembersihan sesi VPN belum terkonfirmasi. Periksa konfigurasi {self.name} di portal eduVPN."
        finally:
            self.session.close()
        return warning


def sanitized_config(raw, repository_ips):
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(raw)
        interface, peer = parser["Interface"], parser["Peer"]
        allowed = [ipaddress.ip_network(x.strip(), strict=False) for x in peer["AllowedIPs"].split(",")]
        for ip in repository_ips:
            if not any(ipaddress.ip_address(ip) in network for network in allowed):
                raise UserError("Profil VPN ini tidak memberi rute ke repository UNAIR.")
        key = interface["PrivateKey"]
        pubkey = peer["PublicKey"]
        if not all(re.fullmatch(r"[A-Za-z0-9+/]{43}=", k) for k in (key, pubkey)):
            raise ValueError("key")
        psk = peer.get("PresharedKey", "").strip()
        if psk and not re.fullmatch(r"[A-Za-z0-9+/]{43}=", psk):
            raise ValueError("psk")
        psk_line = f"PresharedKey = {psk}\n" if psk else ""
        addresses = [str(ipaddress.ip_interface(x.strip())) for x in interface["Address"].split(",")
                     if ipaddress.ip_interface(x.strip()).version == 4]
        if not addresses:
            raise ValueError("address")
        endpoint = peer["Endpoint"]
        if not re.fullmatch(r"[A-Za-z0-9.-]+:\d{1,5}", endpoint):
            raise ValueError("endpoint")
        # Rebuild from validated fields: no hooks, shell commands, default routes, or DNS changes.
        return (f"[Interface]\nPrivateKey = {key}\nAddress = {','.join(addresses)}\nTable = off\n"
                f"[Peer]\nPublicKey = {pubkey}\n{psk_line}AllowedIPs = {','.join(ip + '/32' for ip in repository_ips)}\n"
                f"Endpoint = {endpoint}\nPersistentKeepalive = 25\n")
    except (KeyError, ValueError, configparser.Error):
        raise UserError("Konfigurasi WireGuard dari portal tidak didukung.") from None


def wireproxy_config(raw, bind_port=1080):
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(raw)
        interface, peer = parser["Interface"], parser["Peer"]
        key = interface["PrivateKey"]
        pubkey = peer["PublicKey"]
        if not all(re.fullmatch(r"[A-Za-z0-9+/]{43}=", k) for k in (key, pubkey)):
            raise ValueError("key")
        psk = peer.get("PresharedKey", "").strip()
        if psk and not re.fullmatch(r"[A-Za-z0-9+/]{43}=", psk):
            raise ValueError("psk")
        psk_line = f"PresharedKey = {psk}\n" if psk else ""
        addresses = [str(ipaddress.ip_interface(x.strip())) for x in interface["Address"].split(",")
                     if ipaddress.ip_interface(x.strip()).version == 4]
        if not addresses:
            raise ValueError("address")
        endpoint = peer["Endpoint"]
        if not re.fullmatch(r"[A-Za-z0-9.-]+:\d{1,5}", endpoint):
            raise ValueError("endpoint")
        dns = interface.get("DNS", "1.1.1.1").strip()
        return (f"[Interface]\nPrivateKey = {key}\nAddress = {','.join(addresses)}\nDNS = {dns}\n\n"
                f"[Peer]\nPublicKey = {pubkey}\n{psk_line}Endpoint = {endpoint}\nAllowedIPs = 0.0.0.0/0\n"
                f"PersistentKeepalive = 25\n\n"
                f"[Socks5]\nBindAddress = 127.0.0.1:{bind_port}\n")
    except (KeyError, ValueError, configparser.Error):
        raise UserError("Konfigurasi WireGuard dari portal tidak didukung.") from None


def ensure_wireproxy():
    cmd = shutil.which("wireproxy")
    if cmd:
        return cmd
    tmp_bin = Path(tempfile.gettempdir()) / ("wireproxy.exe" if platform.system() == "Windows" else "wireproxy")
    if tmp_bin.is_file() and (platform.system() == "Windows" or os.access(tmp_bin, os.X_OK)):
        return str(tmp_bin)
    if platform.system() != "Linux":
        return None
    import tarfile
    import urllib.request
    url = "https://github.com/pufferffish/wireproxy/releases/download/v1.0.8/wireproxy_linux_amd64.tar.gz"
    tar_path = Path(tempfile.gettempdir()) / "wireproxy.tar.gz"
    try:
        urllib.request.urlretrieve(url, tar_path)
        with tarfile.open(tar_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith("wireproxy"):
                    f = tar.extractfile(member)
                    if f:
                        tmp_bin.write_bytes(f.read())
                        tmp_bin.chmod(0o755)
                        break
        tar_path.unlink(missing_ok=True)
        return str(tmp_bin) if tmp_bin.is_file() else None
    except Exception:
        return None


class Tunnel:
    def __init__(self):
        self.directory = None
        self.path = None
        self.proc = None
        self.proxy_url = None
        self.wireproxy_bin = ensure_wireproxy()
        self.mode = "wireproxy" if self.wireproxy_bin else "kernel"
        self.started = False

    @staticmethod
    def command(args):
        result = subprocess.run(args, capture_output=True, timeout=30, check=False)
        if result.returncode:
            # wg-quick output can contain key/configuration data: never relay to HTTP/logs.
            raise UserError("VPN server gagal diaktifkan. Periksa WireGuard, izin NET_ADMIN, dan dukungan kernel pada backend.")

    def start(self, config):
        if self.mode == "wireproxy":
            port = 1080
            content = wireproxy_config(config, bind_port=port)
            self.directory = tempfile.TemporaryDirectory(prefix="arsip-wp-")
            self.path = Path(self.directory.name) / "wireproxy.conf"
            self.path.write_text(content, encoding="utf-8")
            self.proc = subprocess.Popen([self.wireproxy_bin, "-c", str(self.path)],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(30):
                if self.proc.poll() is not None:
                    raise UserError("Wireproxy gagal dijalankan. Periksa konfigurasi WireGuard.")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                self.close()
                raise UserError("Wireproxy timeout saat memulai proxy.")
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
                    self.proc.terminate()
                    try:
                        self.proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.proc.kill()
                    self.proc = None
            else:
                if self.started and self.path:
                    self.command(["wg-quick", "down", str(self.path)])
        except Exception:
            success = False
        finally:
            if self.directory:
                self.directory.cleanup()
                self.directory = None
        return success
