import io
import time
import unittest
from unittest.mock import MagicMock, patch

import httpx
import pymupdf
from fastapi.testclient import TestClient
from PIL import Image

from backend import app as worker
from backend.repository import Session, UserError

BASE = 'https://ir.unair.ac.id/uploaded_files/test/index.html'


class AppTests(unittest.TestCase):
    def setUp(self):
        self.settings = patch.multiple(worker, MODE='portal', ACCESS_KEY='fixture-access', OUTPUT_DIR='', network_healthy=True)
        self.settings.start()
        self.client = TestClient(worker.app)
        self.client.__enter__()

    def tearDown(self):
        for job in list(worker.jobs.values()):
            job.directory.cleanup()
        worker.jobs.clear()
        self.client.__exit__(None, None, None)
        self.settings.stop()

    def submit(self):
        response = self.client.post('/jobs', headers={'X-App-Key': 'fixture-access'}, json={
            'url': BASE, 'username': 'fixture-user', 'password': 'fixture-password'})
        self.assertEqual(response.status_code, 202, response.text)
        ticket = response.json()
        return ticket['id'], {'Authorization': 'Bearer ' + ticket['token']}

    def completed(self, identity, headers):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            response = self.client.get('/jobs/' + identity, headers=headers)
            self.assertEqual(response.status_code, 200)
            if worker.jobs[identity].finished:
                return response.json()
            time.sleep(0.01)
        self.fail('Worker did not finish')

    def test_api_pdf_download_authorization_and_cleanup(self):
        picture = io.BytesIO()
        Image.new('RGB', (100, 150), 'white').save(picture, format='JPEG')
        def responder(req):
            if str(req.url).endswith('index.html'):
                return httpx.Response(200, text='<title>Fixture</title>bookConfig.totalPageCount=2;')
            return httpx.Response(200, content=picture.getvalue())
        portal, tunnel = MagicMock(), MagicMock()
        portal.login.return_value = [{'id': 'fixture', 'name': 'Fixture'}]
        portal.close.return_value = None
        tunnel.start.return_value = 'socks5://127.0.0.1:12345'
        tunnel.close.return_value = True
        with patch.object(worker, 'Portal', return_value=portal), patch.object(worker, 'Tunnel', return_value=tunnel), patch.object(worker, 'Session', side_effect=lambda **kw: Session(transport=httpx.MockTransport(responder))):
            identity, headers = self.submit()
            result = self.completed(identity, headers)
        self.assertEqual(result['state'], 'done', result)
        self.assertEqual(result['result']['pages'], 2)
        self.assertEqual(self.client.get(f'/jobs/{identity}/pdf').status_code, 404)
        response = self.client.get(f'/jobs/{identity}/pdf', headers=headers)
        self.assertEqual(response.status_code, 200)
        with pymupdf.open(stream=response.content, filetype='pdf') as document:
            self.assertEqual(len(document), 2)
        path = worker.jobs[identity].pdf
        self.assertEqual(self.client.delete(f'/jobs/{identity}', headers=headers).status_code, 202)
        self.assertFalse(path.exists())
        portal.close.assert_called_once()
        tunnel.close.assert_called_once()
        self.assertFalse(worker.network_lock.locked())

    def test_tunnel_initialization_failure_releases_worker(self):
        with patch.object(worker, 'Tunnel', side_effect=OSError('fixture')):
            identity, headers = self.submit()
            result = self.completed(identity, headers)
        self.assertEqual(result['state'], 'error')
        self.assertFalse(worker.network_lock.locked())

    def test_tunnel_start_failure_closes_portal_and_proxy(self):
        portal, tunnel = MagicMock(), MagicMock()
        portal.login.return_value = [{'id': 'fixture'}]
        portal.close.return_value = None
        tunnel.start.side_effect = UserError('Wireproxy startup fixture')
        tunnel.close.return_value = True
        with patch.object(worker, 'Portal', return_value=portal), patch.object(worker, 'Tunnel', return_value=tunnel):
            identity, headers = self.submit()
            result = self.completed(identity, headers)
        self.assertEqual(result['state'], 'error')
        self.assertFalse(worker.jobs[identity].pdf.exists())
        self.assertFalse(worker.network_lock.locked())
        portal.close.assert_called_once()
        tunnel.close.assert_called_once()

    def test_health_detects_missing_binary(self):
        with patch.object(worker, 'ensure_wireproxy', return_value=None):
            health = self.client.get('/health').json()
        self.assertEqual(health['status'], 'vpn_unavailable')
        self.assertFalse(health['wireproxy_available'])

    def test_worker_can_retry_after_storage_failure(self):
        with patch.object(worker.tempfile, 'TemporaryDirectory', side_effect=OSError('fixture')):
            response = self.client.post('/jobs', headers={'X-App-Key': 'fixture-access'}, json={'url': BASE})
        self.assertEqual(response.status_code, 503)
        self.assertFalse(worker.network_lock.locked())


if __name__ == '__main__':
    unittest.main()
