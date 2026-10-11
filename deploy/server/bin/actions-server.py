#!/usr/bin/env python3
"""The buttons behind the overview page (owner, 11/10/2026).

A small HTTP service on the host, reached by Caddy at /actions/* of the
status site, behind the gate's basic auth: the page is open to read,
the buttons are not. Each action is one of the server's own scripts;
its output is streamed to the browser as it runs, one action at a time.

    GET  /actions/<name>[?branch=..]   a confirmation page
    POST /actions/<name>               runs it, streams the output
"""

import html
import re
import subprocess
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BIN = '/opt/elimelec/bin'
ACTIONS = {
    'rebuild-staging': {
        'label': "Rebuild staging from the latest backup set",
        'cmd': [f'{BIN}/rebuild.sh', 'staging'],
        'warn': "Staging's current database is replaced by the latest backup set, then neutralised and upgraded."},
    'rebuild-dev': {
        'label': "Rebuild dev with a fresh demo database",
        'cmd': [f'{BIN}/rebuild.sh', 'dev'],
        'warn': "Dev's current database is dropped and reinstalled with demo data on its current branch."},
    'deploy-dev': {
        'label': "Deploy a branch to dev",
        'cmd': [f'{BIN}/deploy.sh', 'dev', '{branch}'], 'needs_branch': True,
        'warn': "Dev's clone switches to the branch and the modules are upgraded."},
    'promote-staging': {
        'label': "Promote a dev branch to staging",
        'cmd': [f'{BIN}/promote.sh', '{branch}', 'staging'], 'needs_branch': True,
        'warn': "Refused unless the branch's last test run is green. Fast-forwards the staging branch on GitHub and deploys the staging environment."},
    'promote-prod': {
        'label': "Promote staging to production",
        'cmd': [f'{BIN}/promote.sh', 'staging', 'prod'],
        'warn': "Refused unless staging's last test run is green. Fast-forwards the prod branch on GitHub and deploys PRODUCTION."},
    'backup-now': {
        'label': "Take a daily backup set now",
        'cmd': [f'{BIN}/backup.sh', 'daily', '--full'],
        'warn': "A full set, filestore included, local and off-site."},
}
BRANCH = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._/-]{0,80}$')
PRIVATE = ('127.', '10.', '172.', '192.168.')
lock = threading.Lock()

PAGE = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font:14px/1.5 system-ui,sans-serif;max-width:900px;margin:30px auto;padding:0 16px;color:#1d2433}}
pre{{background:#1e2129;color:#d6d9e0;padding:14px;border-radius:6px;white-space:pre-wrap}}
.btn{{display:inline-block;background:#00a09d;color:#fff;padding:8px 16px;border:0;border-radius:4px;font-size:14px;cursor:pointer}}
a{{color:#00a09d}} .warn{{background:#fff1cc;padding:10px 12px;border-radius:4px}}</style></head><body>{body}</body></html>'''


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'   # the response ends when the script does: no chunking needed

    def _action(self):
        path = urllib.parse.urlparse(self.path)
        name = path.path.rstrip('/').split('/')[-1]
        query = urllib.parse.parse_qs(path.query)
        return name, ACTIONS.get(name), query

    def _send(self, code, body, content_type='text/html; charset=utf-8'):
        data = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self.client_address[0].startswith(PRIVATE):
            return self._send(403, 'forbidden', 'text/plain')
        name, action, query = self._action()
        if not action:
            items = ''.join(f'<li><a href="/actions/{n}">{html.escape(a["label"])}</a></li>' for n, a in ACTIONS.items())
            return self._send(200, PAGE.format(title='Actions', body=f'<h1>Actions</h1><ul>{items}</ul><p><a href="/">Back to the overview</a></p>'))
        branch = (query.get('branch') or [''])[0]
        field = (f'<p><label>Branch <input name="branch" value="{html.escape(branch)}" required pattern="[A-Za-z0-9._/-]+"></label></p>'
                 if action.get('needs_branch') else '')
        body = (f'<h1>{html.escape(action["label"])}</h1><p class="warn">{html.escape(action["warn"])}</p>'
                f'<form method="post" action="/actions/{name}">{field}<button class="btn">Confirm</button></form>'
                f'<p><a href="/">Back to the overview</a></p>')
        self._send(200, PAGE.format(title=action['label'], body=body))

    def do_POST(self):
        if not self.client_address[0].startswith(PRIVATE):
            return self._send(403, 'forbidden', 'text/plain')
        name, action, query = self._action()
        if not action:
            return self._send(404, 'no such action', 'text/plain')
        length = int(self.headers.get('Content-Length') or 0)
        form = urllib.parse.parse_qs(self.rfile.read(length).decode('utf-8')) if length else {}
        branch = (form.get('branch') or query.get('branch') or [''])[0]
        if action.get('needs_branch') and not BRANCH.match(branch):
            return self._send(400, 'a branch name is required', 'text/plain')
        if not lock.acquire(blocking=False):
            return self._send(409, PAGE.format(title='Busy', body='<h1>Another action is running</h1><p>Wait for it to finish, then try again. <a href="/">Back</a></p>'))
        try:
            cmd = [part.replace('{branch}', branch) for part in action['cmd']]
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Accel-Buffering', 'no')
            self.end_headers()
            head = PAGE.split('{body}')[0].format(title=action['label'])
            self.wfile.write((head + f'<h1>{html.escape(action["label"])}</h1><pre>').encode()); self.wfile.flush()
            with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1) as proc:
                for line in proc.stdout:
                    self.wfile.write(html.escape(line).encode('utf-8')); self.wfile.flush()
                code = proc.wait()
            subprocess.run([f'{BIN}/status-page.py'], check=False, timeout=120)
            tail = ('</pre><p><b>Done.</b></p>' if code == 0 else f'</pre><p class="warn"><b>Ended with exit code {code}.</b></p>')
            self.wfile.write((tail + '<p><a href="/">Back to the overview</a></p></body></html>').encode('utf-8'))
        finally:
            lock.release()

    def log_message(self, fmt, *args):  # one line per request, into the service's journal
        print(f'{self.client_address[0]} {fmt % args}', flush=True)


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 8070), Handler).serve_forever()
