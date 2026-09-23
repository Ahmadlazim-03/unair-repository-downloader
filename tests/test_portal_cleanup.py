import unittest
from urllib.parse import parse_qs

import httpx

from backend.repository import Session, UserError, VPN
from backend.vpn import Portal


class PortalCleanupTests(unittest.TestCase):
    def portal(self, responder):
        portal = Portal()
        portal.session.close()
        portal.session = Session('eduvpn.unair.ac.id', transport=httpx.MockTransport(responder))
        portal.created = True
        return portal

    def test_delete_redirect_fragment_and_extension_form(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                removed, posted = [], []
                def responder(req):
                    self.assertNotIn('#', str(req.url))
                    if req.url.path.endswith('_logout'):
                        return httpx.Response(200)
                    if req.method == 'POST':
                        fields = parse_qs(req.content.decode())
                        posted.append(fields)
                        self.assertEqual(fields['connectionId'], ['ours'])
                        if legacy:
                            self.assertTrue(req.url.path.endswith('/deleteConfig'))
                        else:
                            self.assertEqual(fields['action'], ['delete_config'])
                        removed.append(True)
                        return httpx.Response(303, headers={'location': 'home#active-configurations'})
                    if removed:
                        return httpx.Response(200, text='<table><tr><td>another-config</td></tr></table>')
                    delete = ('action="deleteConfig"' if legacy else '')
                    action = '' if legacy else '<input type="hidden" name="action" value="delete_config">'
                    html = f'''<table><tr><td><span title="{portal.name}">truncated-name...</span></td><td>
                        <form method="post"><input type="hidden" name="action" value="extend_config"><input type="hidden" name="connectionId" value="ours"></form>
                        <form method="post" {delete}>{action}<input type="hidden" name="connectionId" value="ours"><input type="hidden" name="csrf" value="fixture-token"></form>
                        </td></tr><tr><td>{portal.name}-other</td><td><form action="deleteConfig"><input type="hidden" name="connectionId" value="not-ours"></form></td></tr></table>'''
                    return httpx.Response(200, text=html)
                portal = self.portal(responder)
                self.assertIsNone(portal.close())
                self.assertEqual(len(posted), 1)
                self.assertEqual(posted[0]['csrf'], ['fixture-token'])
                self.assertFalse(portal.created)

    def test_same_host_fragment_on_initial_form_target(self):
        seen = []
        def responder(req):
            seen.append(str(req.url))
            return httpx.Response(200)
        session = Session('eduvpn.unair.ac.id', transport=httpx.MockTransport(responder))
        try:
            session.request('POST', VPN + 'home#active-configurations', data={'action': 'delete_config'})
            self.assertEqual(seen, [VPN + 'home'])
        finally:
            session.close()

    def test_cross_host_and_http_redirects_still_blocked(self):
        for target in ('https://evil.example/home#active-configurations',
                       'http://eduvpn.unair.ac.id/home#active-configurations',
                       'https://eduvpn.unair.ac.id@evil.example/home#active-configurations'):
            seen = []
            def responder(req):
                seen.append(str(req.url))
                return httpx.Response(307, headers={'location': target})
            session = Session('eduvpn.unair.ac.id', transport=httpx.MockTransport(responder))
            try:
                with self.assertRaises(UserError):
                    session.request('POST', VPN + 'home', data={'password': 'fixture-secret'})
                self.assertEqual(seen, [VPN + 'home'])
            finally:
                session.close()

    def test_http_200_does_not_hide_failed_deletion(self):
        def responder(req):
            if req.url.path.endswith('_logout'):
                return httpx.Response(200)
            return httpx.Response(200, text=f'<table><tr><td>{portal.name}</td><td><form action="deleteConfig"><input type="hidden" name="connectionId" value="ours"></form></td></tr></table>')
        portal = self.portal(responder)
        with self.assertLogs('backend.vpn', level='WARNING'):
            warning = portal.close()
        self.assertIn('belum terkonfirmasi', warning)
        self.assertTrue(portal.created)

    def test_missing_delete_form_never_submits_extension(self):
        posts = []
        def responder(req):
            if req.method == 'POST':
                posts.append(req.url.path)
                return httpx.Response(200)
            return httpx.Response(200, text=f'<table><tr><td>{portal.name}</td><td><form><input type="hidden" name="action" value="extend_config"><input type="hidden" name="connectionId" value="ours"></form></td></tr></table>')
        portal = self.portal(responder)
        with self.assertLogs('backend.vpn', level='WARNING'):
            self.assertIsNotNone(portal.close())
        self.assertEqual(posts, ['/vpn-user-portal/_logout'])

    def test_expired_portal_session_reports_unconfirmed_cleanup(self):
        portal = self.portal(lambda req: httpx.Response(200, text='<form><input name="userPass"></form>'))
        with self.assertLogs('backend.vpn', level='WARNING'):
            self.assertIsNotNone(portal.close())


if __name__ == '__main__':
    unittest.main()
