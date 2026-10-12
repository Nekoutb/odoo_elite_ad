#!/usr/bin/env python3
"""The tick-offs behind elimelecodoo.com/uat (owner, 12/10/2026).

The UAT page is served by Caddy as static files; this small service,
reached at /uat/api/*, keeps each tester's results so the owner can see
who has got how far. One JSON file, one line of log per change, no
accounts: a tester types their name once and the page remembers it.

    GET  /uat/api/state?tester=<name>      {case: {"v": pass|fail|na|null, "n": note}}
    POST /uat/api/state                    {"tester", "case", "v", "n"} -> saved
    GET  /uat/api/summary                  every tester's results
"""

import json
import os
import pathlib
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path('/opt/elimelec/uat')
STORE = ROOT / 'results.json'
LOG = ROOT / 'results.log'
LOCK = threading.Lock()
VALUES = {'pass', 'fail', 'na', None}


def load():
    try:
        return json.loads(STORE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save(data):
    tmp = STORE.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, STORE)


class Handler(BaseHTTPRequestHandler):
    server_version = "elimelec-uat/1"

    def _json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)
        if url.path == '/uat/api/state':
            tester = (query.get('tester') or [''])[0].strip()[:80]
            with LOCK:
                data = load()
            return self._json(200, data.get(tester, {}))
        if url.path == '/uat/api/summary':
            with LOCK:
                data = load()
            return self._json(200, data)
        return self._json(404, {'error': 'not found'})

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        if url.path != '/uat/api/state':
            return self._json(404, {'error': 'not found'})
        try:
            length = int(self.headers.get('Content-Length') or 0)
            payload = json.loads(self.rfile.read(length).decode('utf-8'))
            tester = str(payload.get('tester', '')).strip()[:80]
            case = str(payload.get('case', '')).strip()[:16]
            value = payload.get('v')
            note = str(payload.get('n') or '')[:500]
        except (ValueError, TypeError, UnicodeDecodeError):
            return self._json(400, {'error': 'bad request'})
        if not tester or not case or value not in VALUES:
            return self._json(400, {'error': 'tester, case and v are required'})
        stamp = time.strftime('%Y-%m-%d %H:%M:%S')
        with LOCK:
            data = load()
            data.setdefault(tester, {})[case] = {'v': value, 'n': note, 't': stamp}
            save(data)
            with LOG.open('a', encoding='utf-8') as log:
                log.write("%s\t%s\t%s\t%s\t%s\n" % (stamp, tester, case, value or '-',
                                                     note.replace('\n', ' ')))
        return self._json(200, {'saved': True, 't': stamp})

    def log_message(self, fmt, *args):            # quiet: Caddy has the access log
        pass


if __name__ == '__main__':
    ROOT.mkdir(parents=True, exist_ok=True)
    ThreadingHTTPServer(('0.0.0.0', 8071), Handler).serve_forever()
