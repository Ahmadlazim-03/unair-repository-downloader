import io
import tempfile
import unittest
from pathlib import Path

import httpx
import pymupdf
from PIL import Image

from backend.repository import Session, UserError, input_url, parse_config, build_pdf, resolve_viewer
from backend.vpn import sanitized_config

BASE = 'https://ir.unair.ac.id/uploaded_files/test/index.html'


def picture():
    out = io.BytesIO()
    Image.new('RGB', (100, 150), 'white').save(out, format='JPEG')
    return out.getvalue()


class RepositoryTests(unittest.TestCase):
    def test_input_rejects_external_and_unsafe_urls(self):
        for url in ['http://ir.unair.ac.id/opac/detail-opac', 'https://evil.test/opac/detail-opac',
                    'https://ir.unair.ac.id@evil.test/opac/detail-opac',
                    'https://ir.unair.ac.id:8443/opac/detail-opac',
                    'https://ir.unair.ac.id/uploaded_files/%2e%2e/index.html',
                    'https://ir.unair.ac.id/admin', 'https://ir.unair.ac.id/opac/detail-opac#bad']:
            with self.subTest(url=url), self.assertRaises(UserError):
                input_url(url)
        self.assertEqual(input_url(BASE), BASE)

    def test_redirect_does_not_send_credentials_to_other_host(self):
        seen = []
        def responder(req):
            seen.append(str(req.url))
            return httpx.Response(307, headers={'location': 'https://evil.test/capture'})
        session = Session(transport=httpx.MockTransport(responder))
        with self.assertRaises(UserError):
            session.request('POST', BASE, data={'password':'fixture-secret'})
        self.assertEqual(seen, [BASE])
        session.close()

    def test_response_size_limit(self):
        session = Session(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b'x'*100)))
        with self.assertRaises(UserError):
            session.get(BASE, limit=20)
        session.close()

    def test_config_final_assignment_and_limits(self):
        self.assertEqual(parse_config('bookConfig.totalPageCount=5;bookConfig.totalPageCount="93";bookConfig.normalPath="files/mobile/";', 500), (93,'files/mobile/'))
        for value in ('0','501'):
            with self.assertRaises(UserError):
                parse_config(f'bookConfig.totalPageCount={value}',500)
        with self.assertRaises(UserError):
            parse_config('bookConfig.totalPageCount=1;bookConfig.normalPath="https://evil.test/"',500)

    def test_complete_pdf_and_corrupt_page_failure(self):
        for broken in (False, True):
            def responder(req):
                if req.url.path.endswith('config.js'):
                    return httpx.Response(200,text='bookConfig.totalPageCount=3;')
                if broken and req.url.path.endswith('/2.jpg'):
                    return httpx.Response(200,text='<html>Login required</html>')
                return httpx.Response(200,content=picture())
            session = Session(transport=httpx.MockTransport(responder))
            with tempfile.TemporaryDirectory() as temp:
                output = Path(temp)/'result.pdf'
                if broken:
                    with self.assertRaises(UserError):
                        build_pdf(session,BASE,'Fixture',output,lambda *a:None,lambda:False)
                    self.assertFalse(output.exists())
                else:
                    result = build_pdf(session,BASE,'Fixture',output,lambda *a:None,lambda:False)
                    self.assertEqual(result['pages'],3)
                    with pymupdf.open(output) as doc:
                        self.assertEqual(len(doc),3)
                        self.assertTrue(all(page.get_images() for page in doc))
            session.close()

    def test_cancel_never_publishes_pdf(self):
        session = Session(transport=httpx.MockTransport(lambda req: httpx.Response(200,text='bookConfig.totalPageCount=3;')))
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'cancel.pdf'
            with self.assertRaises(UserError):
                build_pdf(session,BASE,'Fixture',path,lambda *a:None,lambda:True)
            self.assertFalse(path.exists())
        session.close()

    def test_catalog_login_uses_hidden_token_and_session(self):
        submitted=[]
        def responder(req):
            if req.url.path.endswith('/site/loginanggota'):
                submitted.append(req.content.decode())
                return httpx.Response(200,headers={'set-cookie':'authenticated=yes; Path=/'},text='')
            if req.url.path.endswith('/site/login'):
                return httpx.Response(200,text='<form id="login-anggota"><input type="hidden" name="csrf" value="fixture-token"></form>')
            if 'authenticated=yes' in req.headers.get('cookie',''):
                return httpx.Response(200,text=f'<a href="{BASE}">Baca Online</a>')
            return httpx.Response(200,text='<title>Katalog</title>')
        session=Session(transport=httpx.MockTransport(responder))
        viewer,_=resolve_viewer(session,'https://ir.unair.ac.id/opac/detail-opac?id=fixture','test-user','test-pass')
        self.assertEqual(viewer,BASE)
        self.assertIn('csrf=fixture-token',submitted[0])
        session.close()

    def test_wireguard_strips_hooks_and_restricts_routes(self):
        raw='[Interface]\nPrivateKey = '+ 'A'*43 +'=\nAddress = 10.0.0.2/24\nPostUp = do-not-execute\nDNS = 10.0.0.1\n[Peer]\nPublicKey = '+'B'*43+'=\nAllowedIPs = 0.0.0.0/0\nEndpoint = eduvpn.unair.ac.id:51820\n'
        clean=sanitized_config(raw,['192.0.2.5'])
        self.assertNotIn('PostUp',clean)
        self.assertNotIn('DNS',clean)
        self.assertIn('AllowedIPs = 192.0.2.5/32',clean)
        self.assertIn('Table = off',clean)
        with self.assertRaises(UserError):
            sanitized_config(raw.replace('0.0.0.0/0','10.0.0.0/8'),['192.0.2.5'])

    def test_wireproxy_config_generation(self):
        from backend.vpn import wireproxy_config
        raw = '[Interface]\nPrivateKey = ' + 'A'*43 + '=\nAddress = 10.0.0.2/24\nPostUp = evil\nDNS = 10.0.0.1\n[Peer]\nPublicKey = ' + 'B'*43 + '=\nEndpoint = eduvpn.unair.ac.id:51820\n'
        conf = wireproxy_config(raw, bind_port=1080)
        self.assertNotIn('PostUp', conf)
        self.assertIn('[Socks5]', conf)
        self.assertIn('BindAddress = 127.0.0.1:1080', conf)


if __name__ == '__main__':
    unittest.main()
