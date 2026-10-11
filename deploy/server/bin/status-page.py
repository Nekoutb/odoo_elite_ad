#!/usr/bin/env python3
"""The overview page: the three environments side by side, as Odoo.sh
showed them, plus the backups and the server (owner, 11/10/2026).

Writes /opt/elimelec/status/index.html; Caddy serves it at
status.elimelecodoo.com behind the gate. Run every five minutes by cron
and at the end of deploy.sh. Reads only: git, docker, the databases'
module table, the backup status files, the deploy log, and GitHub's
public API for the last test run of each branch.
"""

import datetime as dt
import html
import json
import os
import subprocess
import urllib.request

BASE = '/opt/elimelec'
OUT = f'{BASE}/status/index.html'
ENVS = (
    ('prod', 'Production', 'https://elimelecodoo.com'),
    ('staging', 'Staging', 'https://staging.elimelecodoo.com'),
    ('dev', 'Dev', 'https://dev.elimelecodoo.com'),
)
REPO = 'Nekoutb/odoo_elite_ad'


def sh(cmd, cwd=None, timeout=30):
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              timeout=timeout, check=False).stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        return ''


def read_json(path):
    try:
        with open(path) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def when(iso):
    """'2026-10-11T02:00:12+01:00' -> '11/10/2026 02:00' plus an age."""
    if not iso:
        return '—'
    try:
        moment = dt.datetime.fromisoformat(iso.replace('Z', '+00:00'))
    except ValueError:
        return html.escape(iso)
    now = dt.datetime.now(moment.tzinfo) if moment.tzinfo else dt.datetime.now()
    age = now - moment
    hours = age.total_seconds() / 3600
    ago = (f'{int(age.total_seconds() // 60)} min ago' if hours < 1
           else f'{int(hours)} h ago' if hours < 48 else f'{age.days} d ago')
    return f'{moment.strftime("%d/%m/%Y %H:%M")} <small>({ago})</small>'


def environment(name, label, url):
    folder = f'{BASE}/{name}'
    repo = f'{folder}/repo'
    branch = sh(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=repo) or '—'
    line = sh(['git', 'log', '-1', '--format=%h|%ci|%s'], cwd=repo)
    commit, date, subject = (line.split('|', 2) + ['', '', ''])[:3]
    state = sh(['docker', 'inspect', '-f', '{{.State.Status}}|{{.State.StartedAt}}', f'{name}-odoo'])
    status, started = (state.split('|') + [''])[:2] if state else ('not created', '')
    db = sh(['sed', '-n', 's/^db_name = //p', f'{folder}/odoo.conf'])
    modules, size, health = {}, '', ''
    if status == 'running':
        rows = sh(['docker', 'compose', 'exec', '-T', 'db', 'psql', '-U', 'odoo', '-d', db, '-Atc',
                   "SELECT name || '=' || latest_version FROM ir_module_module "
                   "WHERE name LIKE 'elite%' AND state = 'installed' ORDER BY name"], cwd=folder)
        modules = dict(r.split('=', 1) for r in rows.split() if '=' in r)
        size = sh(['docker', 'compose', 'exec', '-T', 'db', 'psql', '-U', 'odoo', '-d', db, '-Atc',
                   f"SELECT pg_size_pretty(pg_database_size('{db}'))"], cwd=folder)
        health = sh(['docker', 'exec', f'{name}-odoo', 'python3', '-c',
                     "import urllib.request;print(urllib.request.urlopen("
                     "'http://localhost:8069/web/health', timeout=8).status)"], timeout=20)
    deploy = ''
    try:
        with open(f'{BASE}/backups/log/deploys.log') as handle:
            for row in handle:
                if row.split('|')[1:2] == [name]:
                    deploy = row.strip()
    except OSError:
        pass
    return {
        'name': name, 'label': label, 'url': url, 'branch': branch, 'commit': commit,
        'date': date[:16], 'subject': subject, 'status': status, 'started': started,
        'db': db, 'modules': modules, 'size': size, 'healthy': health == '200',
        'deploy': deploy,
    }


def github_runs():
    runs = {}
    for branch in ('staging', 'prod'):
        try:
            req = urllib.request.Request(
                f'https://api.github.com/repos/{REPO}/actions/runs?branch={branch}&per_page=1',
                headers={'User-Agent': 'elimelec-status'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.load(resp)
            run = (data.get('workflow_runs') or [{}])[0]
            runs[branch] = {
                'conclusion': run.get('conclusion') or run.get('status') or '—',
                'sha': (run.get('head_sha') or '')[:7], 'url': run.get('html_url') or '',
                'when': run.get('updated_at') or '',
            }
        except Exception:  # noqa: BLE001 - the page must render without GitHub
            runs[branch] = {'conclusion': 'unreachable', 'sha': '', 'url': '', 'when': ''}
    return runs


def backups():
    env = {}
    try:
        with open(f'{BASE}/backups/backup.env') as handle:
            for row in handle:
                if '=' in row and not row.startswith('#'):
                    key, value = row.strip().split('=', 1)
                    env[key] = value
    except OSError:
        pass
    offsite = ''
    try:
        with open(f'{BASE}/backups/log/backup.log') as handle:
            for row in handle:
                if 'off-site:' in row:
                    offsite = row.split('off-site:', 1)[1].strip()
    except OSError:
        pass
    return {
        'env': env.get('BACKUP_ENV', '—'), 'remote': env.get('RCLONE_REMOTE') or 'none (local only)',
        'daily': read_json(f'{BASE}/backups/status-daily.json'),
        'hourly': read_json(f'{BASE}/backups/status-hourly.json'),
        'test': read_json(f'{BASE}/backups/status-restore-test.json'),
        'offsite': offsite,
        'local': sh(['du', '-sh', f'{BASE}/backups']).split('\t')[0],
    }


def server():
    mem = sh(['free', '-m']).splitlines()
    mem_line = mem[1].split() if len(mem) > 1 else ['', '0', '0']
    disk = sh(['df', '-h', '/']).splitlines()
    disk_line = disk[1].split() if len(disk) > 1 else ['', '', '', '', '']
    return {
        'host': sh(['hostname']), 'uptime': sh(['uptime', '-p']),
        'load': sh(['cat', '/proc/loadavg']).split(' ')[:3],
        'mem_used': mem_line[2], 'mem_total': mem_line[1],
        'disk_used': disk_line[2], 'disk_total': disk_line[1], 'disk_pct': disk_line[4],
        'containers': sh(['docker', 'ps', '--format', '{{.Names}}\t{{.Status}}']).splitlines(),
    }


PILL = {
    'running': 'ok', 'success': 'ok', 'completed': 'ok', 'ok': 'ok',
    'exited': 'bad', 'failure': 'bad', 'not created': 'muted', 'unreachable': 'muted',
}


def pill(text):
    cls = PILL.get(text, 'warn')
    return f'<span class="pill {cls}">{html.escape(text)}</span>'


def render(envs, runs, bk, srv):
    cards = []
    for e in envs:
        mods = ''.join(f'<li><code>{html.escape(k)}</code> {html.escape(v)}</li>' for k, v in e['modules'].items()) \
            or '<li class="muted">no database yet</li>'
        deploy = '—'
        if e['deploy']:
            parts = e['deploy'].split('|')
            deploy = f'{when(parts[0])} <br><small>{html.escape("|".join(parts[2:]))}</small>'
        ci = runs.get(e['branch'], {})
        ci_html = (f'<a href="{html.escape(ci["url"])}">{pill(ci["conclusion"])}</a> <code>{html.escape(ci["sha"])}</code>'
                   if ci else '<span class="muted">no CI for this branch</span>')
        cards.append(f'''
        <section class="card">
          <header>
            <h2>{html.escape(e["label"])}</h2>
            {pill(e["status"] if e["status"] != "running" or e["healthy"] else "running")}
          </header>
          <p class="url"><a href="{e["url"]}">{html.escape(e["url"].replace("https://", ""))}</a></p>
          <dl>
            <dt>Branch</dt><dd><code>{html.escape(e["branch"])}</code> at <code>{html.escape(e["commit"])}</code><br><small>{html.escape(e["subject"])}</small><br><small>{html.escape(e["date"])}</small></dd>
            <dt>Tests on branch</dt><dd>{ci_html}</dd>
            <dt>Modules</dt><dd><ul>{mods}</ul></dd>
            <dt>Database</dt><dd><code>{html.escape(e["db"])}</code> {html.escape(e["size"])}</dd>
            <dt>Odoo up since</dt><dd>{when(e["started"]) if e["started"] else "—"}</dd>
            <dt>Last deploy</dt><dd>{deploy}</dd>
          </dl>
        </section>''')

    def bk_row(label, item, extra=''):
        if not item:
            return f'<tr><td>{label}</td><td colspan="3" class="muted">never</td></tr>'
        result = item.get('result') or 'ok'
        return (f'<tr><td>{label}</td><td>{pill(result)}</td>'
                f'<td>{when(item.get("finished"))}</td><td><small>{html.escape(extra or item.get("set", ""))}</small></td></tr>')

    test = bk['test']
    test_extra = f'set {test.get("set", "")} from {test.get("source", "")}: {test.get("moves", "?")} entries, {test.get("files", "?")} files' if test else ''
    containers = ''.join(f'<li><code>{html.escape(c.split(chr(9))[0])}</code> <small>{html.escape(c.split(chr(9))[1] if chr(9) in c else "")}</small></li>'
                         for c in srv['containers'])
    now = dt.datetime.now().strftime('%d/%m/%Y %H:%M')
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>Elimelec Odoo</title>
<style>
:root {{ --bg:#f4f5f8; --card:#fff; --ink:#1d2433; --muted:#6b7280; --line:#e3e6ec; --ok:#1a7f4b; --okbg:#dff5e8; --bad:#b4232c; --badbg:#fde3e5; --warn:#8a5a00; --warnbg:#fff1cc; --accent:#714b67; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#14161c; --card:#1d2029; --ink:#e7e9ee; --muted:#9aa1ad; --line:#2d313c; --okbg:#153d2a; --ok:#6fd69d; --badbg:#48191d; --bad:#ff8a93; --warnbg:#3e2f0b; --warn:#ffd272; --accent:#b48fb0; }} }}
* {{ box-sizing:border-box }} body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
.top {{ background:var(--accent); color:#fff; padding:14px 24px; display:flex; justify-content:space-between; align-items:baseline; flex-wrap:wrap; gap:8px }}
.top h1 {{ margin:0; font-size:18px; font-weight:600 }} .top small {{ opacity:.85 }}
main {{ padding:20px 24px; max-width:1400px; margin:0 auto }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(320px, 1fr)); gap:16px }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px 18px }}
.card header {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:4px }}
.card h2 {{ margin:0; font-size:16px }} .url {{ margin:0 0 10px; }} .url a {{ color:var(--accent); text-decoration:none }}
dl {{ display:grid; grid-template-columns:auto 1fr; gap:6px 12px; margin:0 }} dt {{ color:var(--muted); white-space:nowrap }} dd {{ margin:0 }}
ul {{ margin:0; padding-left:16px }} code {{ font-family:ui-monospace, Menlo, Consolas, monospace; font-size:12.5px }}
small {{ color:var(--muted) }} .muted {{ color:var(--muted) }}
.pill {{ display:inline-block; padding:2px 9px; border-radius:999px; font-size:12px; font-weight:600 }}
.pill.ok {{ background:var(--okbg); color:var(--ok) }} .pill.bad {{ background:var(--badbg); color:var(--bad) }}
.pill.warn {{ background:var(--warnbg); color:var(--warn) }} .pill.muted {{ background:var(--line); color:var(--muted) }}
h3 {{ font-size:14px; margin:24px 0 10px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em }}
table {{ width:100%; border-collapse:collapse }} td, th {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top }}
.two {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(360px, 1fr)); gap:16px }}
a {{ color:inherit }}
</style></head>
<body>
<div class="top"><h1>Elimelec Odoo — environments</h1><small>{srv["host"]} · refreshed {now} · every 5 minutes</small></div>
<main>
<div class="grid">{"".join(cards)}</div>

<h3>Backups</h3>
<div class="two">
<section class="card">
<table>
<tr><th>Job</th><th>Result</th><th>Last run</th><th>Detail</th></tr>
{bk_row("Daily set", bk["daily"])}
{bk_row("Hourly dump", bk["hourly"])}
{bk_row("Restore test", test, test_extra)}
</table>
<p><small>Backing up <b>{html.escape(bk["env"])}</b> · off-site to <code>{html.escape(bk["remote"])}</code> · in the bucket: {html.escape(bk["offsite"] or "—")} · on this disk: {html.escape(bk["local"])}</small></p>
<p><small>Schedule: daily 02:00 · hourly 07:00–20:00 Mon–Sat · restore test Sunday 03:30. Policy: docs/backup-policy.md.</small></p>
</section>
<section class="card">
<dl>
<dt>Uptime</dt><dd>{html.escape(srv["uptime"])}</dd>
<dt>Load</dt><dd>{html.escape(" ".join(srv["load"]))} <small>(4 cores)</small></dd>
<dt>Memory</dt><dd>{html.escape(srv["mem_used"])} MB of {html.escape(srv["mem_total"])} MB</dd>
<dt>Disk</dt><dd>{html.escape(srv["disk_used"])} of {html.escape(srv["disk_total"])} ({html.escape(srv["disk_pct"])})</dd>
<dt>Containers</dt><dd><ul>{containers}</ul></dd>
</dl>
</section>
</div>
<p><small>Code: <a href="https://github.com/{REPO}/branches">branches</a> · <a href="https://github.com/{REPO}/actions">test runs</a>. Deploy: <code>deploy.sh &lt;env&gt;</code> on the server.</small></p>
</main></body></html>'''


def main():
    envs = [environment(*e) for e in ENVS]
    page = render(envs, github_runs(), backups(), server())
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as handle:
        handle.write(page)
    os.replace(tmp, OUT)


if __name__ == '__main__':
    main()
