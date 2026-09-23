import base64
import configparser
import os
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup

from backend.repository import UserError
from backend.vpn import Portal, Tunnel, ensure_wireproxy, extract_wireguard_config, wireproxy_config, wireproxy_failure

KEY = base64.b64encode(bytes(range(32))).decode()
RAW = f'''[Interface]
PrivateKey = {KEY}
Address = 10.0.0.2/24, fd00::2/64
DNS = 10.0.0.1, fd00::1, unair.ac.id
MTU = 1280
PostUp = never-execute
[Peer]
PublicKey = {KEY}
PresharedKey = {KEY}
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = 127.0.0.1:51820
'''


class ConfigTests(unittest.TestCase):
    def test_portal_dns_search_domain_and_wireguard_fields(self):
        config = configparser.ConfigParser()
        config.read_string(wireproxy_config(RAW, 12345))
        self.assertEqual(config['Interface']['DNS'], '10.0.0.1, fd00::1')
        self.assertEqual(config['Interface']['Address'], '10.0.0.2/24,fd00::2/64')
        self.assertEqual(config['Interface']['MTU'], '1280')
        self.assertNotIn('PostUp', config['Interface'])
        self.assertEqual(config['Peer']['PersistentKeepalive'], '25')
        self.assertEqual(config['Peer']['PreSharedKey'], KEY)
        self.assertEqual(config['Peer']['AllowedIPs'], '0.0.0.0/0,::/0')

    def test_ipv6_endpoint(self):
        self.assertIn('Endpoint = [::1]:51820', wireproxy_config(RAW.replace('127.0.0.1:51820', '[::1]:51820')))

    def test_invalid_input_never_discloses_secrets(self):
        for raw in (RAW.replace(KEY, 'private-secret!'), RAW.replace('MTU = 1280', 'private-secret!'),
                    RAW.replace('51820', '99999')):
            with self.assertRaises(UserError) as caught:
                wireproxy_config(raw)
            self.assertNotIn('private-secret!', str(caught.exception))
            self.assertNotIn(KEY, str(caught.exception))

    def test_diagnostic_classification_does_not_echo_raw_config(self):
        for text, expected in [('invalid key: private-secret!', 'Key WireGuard'),
                               ('address already in use', 'Port proxy'),
                               ('lookup endpoint: no such host', 'DNS backend'),
                               ('ParseAddr(unair.ac.id)', 'Alamat IP'),
                               ('operation not permitted', 'socket UDP')]:
            with self.assertLogs('backend.vpn', level='ERROR') as logs:
                error = wireproxy_failure(text + '\nPrivateKey=' + KEY, 'startup', 1)
            self.assertIn(expected, str(error))
            self.assertNotIn(KEY, str(error) + ''.join(logs.output))
            self.assertNotIn('private-secret!', str(error) + ''.join(logs.output))

    def test_mobileconfig_extraction(self):
        payload = base64.b64encode(('<plist><key>WgQuickConfig</key><string>' + RAW + '</string></plist>').encode()).decode()
        html = f'<a href="data:application/x-apple-aspen-config;base64,{payload}">download</a>'
        self.assertEqual(extract_wireguard_config(html), RAW.strip())

    def test_full_quota_does_not_delete_existing_configs(self):
        portal = Portal()
        login = BeautifulSoup('<form><input name="userName"></form>', 'html.parser')
        quota = BeautifulSoup('<tr><td>arsip-other-user</td><form><input type="hidden" name="action" value="deleteConfig"></form></tr>', 'html.parser')
        with patch.object(portal.session, 'html', side_effect=[(login, 'https://eduvpn.unair.ac.id/'), (quota, 'https://eduvpn.unair.ac.id/')]), patch.object(portal, 'post') as post:
            with self.assertRaises(UserError):
                portal.login('fixture', 'fixture')
            self.assertEqual(post.call_count, 1)  # Login only, never delete another config.
        portal.session.close()

    def test_binary_is_required_without_runtime_download(self):
        with patch('backend.vpn.ensure_wireproxy', return_value=None):
            tunnel = Tunnel()
            with self.assertRaisesRegex(UserError, 'Binary Wireproxy'):
                tunnel.start(RAW)
            self.assertTrue(tunnel.close())


@unittest.skipUnless(ensure_wireproxy(), 'Set WIREPROXY_BIN to run against a real Wireproxy binary')
class BinaryTests(unittest.TestCase):
    def test_real_parser_accepts_normalized_portal_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'fixture.conf'
            config.write_text(wireproxy_config(RAW), encoding='utf-8')
            result = subprocess.run([ensure_wireproxy(), '-n', '-c', str(config)], capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, 'Wireproxy rejected normalized config')

    def test_old_dns_search_domain_reproduces_startup_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'fixture.conf'
            # The old converter passed the portal DNS search suffix to Wireproxy as an IP.
            config.write_text(wireproxy_config(RAW).replace('DNS = 10.0.0.1, fd00::1', 'DNS = 10.0.0.1, unair.ac.id'), encoding='utf-8')
            result = subprocess.run([ensure_wireproxy(), '-n', '-c', str(config)], capture_output=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'ParseAddr', result.stdout + result.stderr)

    def test_real_socks_start_stop_and_parallel_tunnels(self):
        # Endpoint is localhost with fixture keys: no campus credentials or VPN connection needed.
        first, second = Tunnel(), Tunnel()
        try:
            urls = [first.start(RAW), second.start(RAW)]
            self.assertNotEqual(*urls)
            processes = [first.proc, second.proc]
            paths = [first.path, second.path]
            ports = [int(url.rsplit(':', 1)[1]) for url in urls]
        finally:
            self.assertTrue(first.close())
            self.assertTrue(second.close())
        self.assertTrue(all(proc.poll() is not None for proc in processes))
        self.assertTrue(all(not path.exists() for path in paths))
        for port in ports:
            with socket.socket() as probe:
                probe.settimeout(0.2)
                self.assertNotEqual(probe.connect_ex(('127.0.0.1', port)), 0)


if __name__ == '__main__':
    unittest.main()
