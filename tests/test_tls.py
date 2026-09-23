import hashlib
from pathlib import Path
import ssl
import unittest

import httpx

from backend.repository import tls_context, connection_error


class TLSTests(unittest.TestCase):
    def test_repository_still_requires_hostname_and_full_trusted_chain(self):
        for host in ('ir.unair.ac.id', 'eduvpn.unair.ac.id'):
            context = tls_context(host)
            self.assertTrue(context.check_hostname)
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertFalse(context.verify_flags & ssl.VERIFY_X509_PARTIAL_CHAIN)

    def test_public_intermediate_matches_verified_official_download(self):
        pem = (Path(__file__).resolve().parents[1] / 'backend/certs/sectigo-dv-r36.pem').read_text()
        self.assertEqual(hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest(),
                         '8c54c334b66ba4e426772af4a3f9136c19a1aec729fdb28c535c07a5a4ef22e0')

    def test_transport_errors_are_distinguished_without_echoing_credentials(self):
        cases = [
            (httpx.ConnectError('[SSL: CERTIFICATE_VERIFY_FAILED] password=secret'), 'sertifikat'),
            (httpx.ProxyError('password=secret'), 'Proxy VPN'),
            (httpx.ConnectTimeout('password=secret'), 'sebelum HTTPS'),
            (httpx.ReadTimeout('password=secret'), 'setelah koneksi'),
        ]
        for exc, expected in cases:
            message = connection_error(exc, via_vpn=True)
            self.assertIn(expected, message)
            self.assertNotIn('secret', message)


if __name__ == '__main__':
    unittest.main()
