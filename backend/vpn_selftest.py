"""Check the real Wireproxy runtime without a campus account or external VPN.

Run as the same unprivileged user used by the API, both at image build time and
container startup: the builder's kernel/security policy may differ from the host.
"""
import base64
import secrets

from .vpn import Tunnel


def selftest():
    private = base64.b64encode(secrets.token_bytes(32)).decode('ascii')
    public = base64.b64encode(secrets.token_bytes(32)).decode('ascii')
    raw = (f'[Interface]\nPrivateKey = {private}\nAddress = 192.0.2.2/32\n'
           f'[Peer]\nPublicKey = {public}\nAllowedIPs = 192.0.2.0/24\n'
           'Endpoint = 127.0.0.1:51820\n')
    tunnel = Tunnel()
    try:
        tunnel.start(raw)
    finally:
        if not tunnel.close():
            raise RuntimeError('Wireproxy self-test cleanup failed')
    print('Wireproxy runtime self-test passed (SOCKS5 and cleanup).', flush=True)


if __name__ == '__main__':
    selftest()
