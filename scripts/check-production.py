"""Actual production download check. Secrets come from prompts or environment."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import time

import httpx
import pymupdf


def check(api, url, username, password, access_key, output, expected_pages=None):
    api = api.rstrip('/')
    if not api.startswith('https://'):
        raise ValueError('Production API must use HTTPS')
    start = time.monotonic()
    ticket = None
    with httpx.Client(timeout=60, follow_redirects=False) as client:
        def request(method, path, **kwargs):
            response = client.request(method, api + path, **kwargs)
            if response.is_error:
                # Do not print request bodies, response HTML, or credentials.
                raise RuntimeError(f'API {path.split("/")[1]} returned HTTP {response.status_code}')
            return response
        health = request('GET', '/health').json()
        print('Backend revision:', health.get('revision'), flush=True)
        headers = {'X-App-Key': access_key}
        profiles = request('POST', '/vpn/profiles', headers=headers,
                           json={'username': username, 'password': password}).json()['profiles']
        available = [p for p in profiles if not p['id'].endswith('+tcp')]
        if len(available) != 1:
            raise RuntimeError('Expected one supported VPN profile for this check')
        try:
            ticket = request('POST', '/jobs', headers=headers, json={
                'url': url, 'username': username, 'password': password,
                'profile_id': available[0]['id']}).json()
            auth = {'Authorization': 'Bearer ' + ticket['token']}
            path = '/jobs/' + ticket['id']
            deadline = time.monotonic() + 600
            previous = None
            while time.monotonic() < deadline:
                status = request('GET', path, headers=auth).json()
                state = (status['state'], status['current'], status['total'])
                if state != previous:
                    print(*state, flush=True)
                    previous = state
                if status['state'] in ('error', 'cancelled'):
                    raise RuntimeError(status['message'])
                if status['state'] == 'done':
                    break
                time.sleep(2)
            else:
                raise RuntimeError('Production job exceeded 10 minutes')
            if status.get('warning'):
                raise RuntimeError('Production cleanup is not confirmed: ' + status['warning'])
            body = request('GET', path + '/pdf', headers=auth).content
            with pymupdf.open(stream=body, filetype='pdf') as document:
                pages = len(document)
                if pages != status['result']['pages'] or not all(p.get_images() for p in document):
                    raise RuntimeError('Downloaded PDF is incomplete')
                if expected_pages is not None and pages != expected_pages:
                    raise RuntimeError(f'Expected {expected_pages} pages, got {pages}')
            output = Path(output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(body)
            report = {'api': api, 'revision': health.get('revision'), 'pages': pages,
                      'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
                      'seconds': round(time.monotonic() - start, 1), 'cleanup_warning': None}
            output.with_suffix('.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            print('PRODUCTION CHECK PASSED:', json.dumps(report), flush=True)
            return report
        finally:
            if ticket is not None:
                request('DELETE', '/jobs/' + ticket['id'], headers={'Authorization': 'Bearer ' + ticket['token']})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api', default='https://unairrepositorydownloader-d6x2bsd9.b4a.run')
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', default='.runtime/production-verified.pdf')
    parser.add_argument('--expected-pages', type=int)
    args = parser.parse_args()
    check(args.api, args.url,
          os.getenv('UNAIR_USERNAME') or input('NIM / username: '),
          os.getenv('UNAIR_PASSWORD') or getpass.getpass('Password kampus: '),
          os.getenv('APP_ACCESS_KEY') or getpass.getpass('Kode akses aplikasi: '),
          args.output, args.expected_pages)
