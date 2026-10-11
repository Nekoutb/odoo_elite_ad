#!/usr/bin/env python3
"""The overview page, in the shape of the Odoo.sh console (owner,
11/10/2026): a sidebar with Production / Staging / Development, each
branch with its status light, and for the selected one the tabs
History, Backups, Monitor, Logs.

Writes /opt/elimelec/status/index.html, a single page with its data
embedded; Caddy serves it at status.elimelecodoo.com, with no gate. Run
every five minutes by cron and at the end of deploy.sh. Reads only:
git, docker, the databases' module table, the backup folders and the
bucket listing, the deploy log, and GitHub's public API (two calls).
"""

import datetime as dt
import html
import json
import os
import subprocess
import urllib.request

BASE = '/opt/elimelec'
OUT = f'{BASE}/status/index.html'
REPO = 'Nekoutb/odoo_elite_ad'
ENVS = (
    ('prod', 'Production', 'https://elimelecodoo.com', 'prod'),
    ('staging', 'Staging', 'https://staging.elimelecodoo.com', 'staging'),
    ('dev', 'Development', 'https://dev.elimelecodoo.com', 'dev'),
)
ODOO_SERIES = '19.0'


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


def stamp(iso, with_age=False):
    if not iso:
        return '—'
    try:
        moment = dt.datetime.fromisoformat(iso.replace('Z', '+00:00'))
    except ValueError:
        return html.escape(iso[:16])
    if moment.tzinfo:
        moment = moment.astimezone()
    text = moment.strftime('%Y-%m-%d %H:%M:%S')
    if with_age:
        age = dt.datetime.now(moment.tzinfo) - moment
        hours = age.total_seconds() / 3600
        ago = (f'{int(age.total_seconds() // 60)} min ago' if hours < 1
               else f'{int(hours)} h ago' if hours < 48 else f'{age.days} d ago')
        text += f' <small>({ago})</small>'
    return text


# ----------------------------------------------------------------- sources
def github():
    """Every branch with its last test run: two public API calls."""
    def get(path):
        req = urllib.request.Request(f'https://api.github.com/repos/{REPO}{path}',
                                     headers={'User-Agent': 'elimelec-status'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp)
    branches, runs, by_sha = [], {}, {}
    try:
        branches = [(b['name'], b['commit']['sha'][:7]) for b in get('/branches?per_page=100')]
        for run in get('/actions/runs?per_page=100').get('workflow_runs', []):
            entry = {'state': run.get('conclusion') or run.get('status') or '',
                     'sha': run['head_sha'][:7], 'url': run['html_url'], 'when': run['updated_at']}
            runs.setdefault(run['head_branch'], entry)
            by_sha.setdefault(run['head_sha'][:7], entry)
    except Exception:  # noqa: BLE001 - the page must render without GitHub
        pass
    return branches, runs, by_sha


def environment(name, label, url, group):
    folder = f'{BASE}/{name}'
    repo = f'{folder}/repo'
    branch = sh(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=repo) or '—'
    commits = []
    for row in sh(['git', 'log', '-12', '--format=%h|%ci|%an|%s'], cwd=repo).splitlines():
        parts = row.split('|', 3)
        if len(parts) == 4:
            commits.append(parts)
    state = sh(['docker', 'inspect', '-f', '{{.State.Status}}|{{.State.StartedAt}}', f'{name}-odoo'])
    status, started = (state.split('|') + [''])[:2] if state else ('not created', '')
    db = sh(['sed', '-n', 's/^db_name = //p', f'{folder}/odoo.conf'])
    modules, size, healthy = {}, '', False
    if status == 'running':
        rows = sh(['docker', 'compose', 'exec', '-T', 'db', 'psql', '-U', 'odoo', '-d', db, '-Atc',
                   "SELECT name || '=' || latest_version FROM ir_module_module "
                   "WHERE name LIKE 'elite%' AND state = 'installed' ORDER BY name"], cwd=folder)
        modules = dict(r.split('=', 1) for r in rows.split() if '=' in r)
        size = sh(['docker', 'compose', 'exec', '-T', 'db', 'psql', '-U', 'odoo', '-d', db, '-Atc',
                   f"SELECT pg_size_pretty(pg_database_size('{db}'))"], cwd=folder)
        healthy = sh(['docker', 'exec', f'{name}-odoo', 'python3', '-c',
                      "import urllib.request;print(urllib.request.urlopen("
                      "'http://localhost:8069/web/health', timeout=8).status)"], timeout=20) == '200'
    deploys = []
    try:
        with open(f'{BASE}/backups/log/deploys.log') as handle:
            for row in handle:
                parts = row.strip().split('|')
                if len(parts) >= 4 and parts[1] == name:
                    deploys.append(parts)
    except OSError:
        pass
    light = 'green' if status == 'running' and healthy else 'red' if status == 'running' else 'grey'
    return {
        'name': name, 'label': label, 'url': url, 'group': group, 'branch': branch,
        'commits': commits, 'status': status, 'started': started, 'db': db,
        'modules': modules, 'size': size, 'healthy': healthy, 'deploys': deploys[-10:][::-1],
        'light': light,
    }


def backup_rows():
    env = {}
    try:
        with open(f'{BASE}/backups/backup.env') as handle:
            for row in handle:
                if '=' in row and not row.startswith('#'):
                    key, value = row.strip().split('=', 1)
                    env[key] = value
    except OSError:
        pass
    target = env.get('BACKUP_ENV', 'prod')
    remote = env.get('RCLONE_REMOTE', '')
    rows = []
    root = f'{BASE}/backups/{target}'
    for kind in ('daily', 'hourly'):
        folder = f'{root}/{kind}'
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder), reverse=True):
            manifest = read_json(f'{folder}/{name}/manifest.json')
            size = sh(['du', '-sh', f'{folder}/{name}']).split('\t')[0]
            full = os.path.exists(f'{folder}/{name}/filestore.tar.zst')
            rows.append({
                'time': name.replace('_', ' ').replace(' ', ' ', 1), 'db': manifest.get('db') or '',
                'env': target, 'kind': kind, 'full': full, 'size': size,
                'modules': manifest.get('modules') or {}, 'commit': manifest.get('commit') or '',
                'where': 'here', 'key': f'{kind}/{name}',
            })
    offsite = set()
    if remote:
        for kind in ('daily', 'hourly'):
            for entry in sh(['rclone', 'lsf', '--dirs-only', f'{remote}/{target}/{kind}'], timeout=60).split():
                offsite.add(f'{kind}/{entry.strip("/")}')
    for row in rows:
        if row['key'] in offsite:
            row['where'] = 'here + off-site'
    local_keys = {r['key'] for r in rows}
    for key in sorted(offsite - local_keys, reverse=True):
        kind, name = key.split('/', 1)
        rows.append({'time': name.replace('_', ' '), 'db': '', 'env': target, 'kind': kind, 'full': False,
                     'size': '', 'modules': {}, 'commit': '', 'where': 'off-site', 'key': key})
    rows.sort(key=lambda r: r['key'].split('/', 1)[1], reverse=True)
    return {
        'rows': rows[:60], 'target': target, 'remote': remote or 'none',
        'daily': read_json(f'{BASE}/backups/status-daily.json'),
        'hourly': read_json(f'{BASE}/backups/status-hourly.json'),
        'test': read_json(f'{BASE}/backups/status-restore-test.json'),
    }


def monitor():
    mem = sh(['free', '-m']).splitlines()
    mem_line = mem[1].split() if len(mem) > 1 else ['', '0', '0']
    disk = sh(['df', '-h', '/']).splitlines()
    disk_line = disk[1].split() if len(disk) > 1 else ['', '', '', '', '']
    return {
        'host': sh(['hostname']), 'uptime': sh(['uptime', '-p']),
        'load': ' '.join(sh(['cat', '/proc/loadavg']).split(' ')[:3]),
        'mem_used': mem_line[2], 'mem_total': mem_line[1],
        'disk_used': disk_line[2], 'disk_total': disk_line[1], 'disk_pct': disk_line[4],
        'containers': [c.split('\t') for c in sh(['docker', 'ps', '-a', '--format', '{{.Names}}\t{{.Status}}']).splitlines()],
    }


def logs():
    out = {}
    for label, path in (('backups', f'{BASE}/backups/log/backup.log'),
                        ('deploys', f'{BASE}/backups/log/deploys.log'),
                        ('cron', f'{BASE}/backups/log/cron.log')):
        try:
            with open(path, errors='replace') as handle:
                out[label] = handle.readlines()[-40:]
        except OSError:
            out[label] = []
    return out


# ------------------------------------------------------------------ render
def light(colour, title=''):
    return f'<span class="light {colour}" title="{html.escape(title)}"></span>'


def ci_light(run):
    if not run:
        return 'grey', 'no test run'
    state = run['state']
    return ('green' if state == 'success' else 'red' if state == 'failure'
            else 'orange'), state


def render(envs, branches, runs, by_sha, bk, mon, lg):
    e = html.escape

    def rev(sha):
        """A revision with the colour of its test run beside it."""
        if not sha:
            return '—'
        run = by_sha.get(sha[:7])
        colour, title = ci_light(run)
        link = f'<a href="{e(run["url"])}" title="tests: {e(title)}">' if run else ''
        return f'<code>{e(sha[:7])}</code> {link}{light(colour, "tests: " + title)}{"</a>" if run else ""}'

    def button(action, label, kind='', branch=''):
        hidden = f'<input type="hidden" name="branch" value="{e(branch)}">' if branch else ''
        ask = json.dumps(label + "?")
        return (f'<form method="post" action="/actions/{action}" class="act" '
                f"onsubmit='return confirm({ask})'>{hidden}<button class=\"btn {kind}\">{e(label)}</button></form>")
    # ---------------------------------------------------------- sidebar
    def side_row(key, name, colour, title, extra=''):
        return (f'<a class="branch" data-target="{e(key)}" href="#{e(key)}">'
                f'<span class="bn">{e(name)}</span><span class="bv">{ODOO_SERIES}</span>{light(colour, title)}{extra}</a>')
    env_by_group = {env['group']: env for env in envs}
    side = ['<div class="group">Production</div>', side_row('prod', env_by_group['prod']['branch'], env_by_group['prod']['light'], env_by_group['prod']['status']),
            '<div class="group">Staging</div>', side_row('staging', env_by_group['staging']['branch'], env_by_group['staging']['light'], env_by_group['staging']['status']),
            '<div class="group">Development</div>', side_row('dev', f'dev ({env_by_group["dev"]["branch"]})', env_by_group['dev']['light'], env_by_group['dev']['status'])]
    dev_branches = [b for b in branches if b[0].startswith('dev/')]
    for name, sha in sorted(dev_branches, key=lambda b: (runs.get(b[0], {}).get('when') or ''), reverse=True):
        colour, title = ci_light(runs.get(name))
        side.append(side_row(f'branch:{name}', name, colour, f'tests: {title}'))

    # ---------------------------------------------------------- panels
    panels = []
    backups_table = ['<table><tr><th>Time</th><th>Database</th><th>Environment</th><th>Version</th><th>Comment</th><th>Revision</th><th>Size</th><th>Where</th></tr>']
    for row in bk['rows']:
        comment = {'daily': 'Automatic daily set' + (' + filestore' if row['full'] else ''), 'hourly': 'Hourly dump'}[row['kind']]
        version = row['modules'].get('elite_clearance', '')
        backups_table.append(f'<tr><td>{e(row["time"])}</td><td>{e(row["db"])}</td><td>{e(row["env"])}</td><td>{e(version)}</td>'
                             f'<td><span class="tag">{e(comment)}</span></td><td>{rev(row["commit"])}</td><td>{e(row["size"])}</td><td>{e(row["where"])}</td></tr>')
    backups_table.append('</table>')
    test = bk['test']
    jobs = ''.join(
        f'<tr><td>{label}</td><td>{light("green" if item else "grey")} {e((item.get("result") or "ok") if item else "never")}</td><td>{stamp(item.get("finished"), True) if item else "—"}</td><td><small>{e(detail)}</small></td></tr>'
        for label, item, detail in (
            ('Daily set', bk['daily'], bk['daily'].get('set', '')),
            ('Hourly dump', bk['hourly'], bk['hourly'].get('set', '')),
            ('Restore test', test, f'set {test.get("set", "")} from {test.get("source", "")}: {test.get("moves", "?")} entries, {test.get("files", "?")} files' if test else '')))
    backups_html = (f'<div class="bar"><span>Backing up <b>{e(bk["target"])}</b> · off-site: <code>{e(bk["remote"])}</code> · '
                    f'daily 02:00 · hourly 07:00–20:00 Mon–Sat · restore test Sunday 03:30</span></div>'
                    f'<table class="jobs"><tr><th>Job</th><th>Result</th><th>Last run</th><th>Detail</th></tr>{jobs}</table>'
                    + ''.join(backups_table))
    monitor_html = (f'<dl><dt>Host</dt><dd>{e(mon["host"])}</dd><dt>Uptime</dt><dd>{e(mon["uptime"])}</dd>'
                    f'<dt>Load</dt><dd>{e(mon["load"])} <small>(4 cores)</small></dd>'
                    f'<dt>Memory</dt><dd>{e(mon["mem_used"])} MB of {e(mon["mem_total"])} MB</dd>'
                    f'<dt>Disk</dt><dd>{e(mon["disk_used"])} of {e(mon["disk_total"])} ({e(mon["disk_pct"])})</dd></dl>'
                    '<table><tr><th>Container</th><th>Status</th></tr>'
                    + ''.join(f'<tr><td><code>{e(c[0])}</code></td><td>{e(c[1] if len(c) > 1 else "")}</td></tr>' for c in mon['containers'])
                    + '</table>')
    logs_html = ''.join(f'<h4>{e(label)}</h4><pre>{e("".join(lines)) or "—"}</pre>' for label, lines in lg.items())

    for env in envs:
        run = runs.get(env['branch'], {})
        colour, title = ci_light(run)
        mods = ', '.join(f'{k} {v}' for k, v in env['modules'].items()) or 'no database'
        actions = {
            'prod': button('promote-prod', "Promote staging → production", 'danger'),
            'staging': button('rebuild-staging', "Rebuild from the latest backup") + button('backup-now', "Backup now"),
            'dev': button('rebuild-dev', "Rebuild with demo data"),
        }[env['name']]
        head = (f'<div class="head"><h2>{e(env["branch"])}</h2>'
                f'<span class="st">{light(env["light"], env["status"])} {e(env["status"])}</span>'
                f'<span class="acts">{actions}<a class="btn connect" href="{env["url"]}/odoo">Connect</a></span></div>'
                f'<div class="facts"><span>Odoo {ODOO_SERIES} Community</span><span>{e(mods)}</span>'
                f'<span>database <code>{e(env["db"])}</code> {e(env["size"])}</span>'
                f'<span>revision {rev(env["commits"][0][0] if env["commits"] else "")}</span>'
                f'<span>up since {stamp(env["started"], True) if env["started"] else "—"}</span>'
                f'<span>tests on branch: {light(colour, title)} {e(title)}' + (f' <a href="{e(run["url"])}">see run</a>' if run else '') + '</span></div>')
        history = ['<h4>Deploys</h4><table><tr><th>When</th><th>Branch, revision</th><th>Result</th></tr>']
        for parts in env['deploys']:
            moved = parts[2].split(' ')[-1]
            history.append(f'<tr><td>{stamp(parts[0])}</td><td>{e(parts[2].split(" ")[0])} {e(moved.split("->")[0])} → {rev(moved.split("->")[-1])}</td><td>{e(parts[3])}</td></tr>')
        if not env['deploys']:
            history.append('<tr><td colspan="3"><small>no deploy recorded yet</small></td></tr>')
        history.append('</table><h4>Commits on the branch</h4><table><tr><th>Revision</th><th>Date</th><th>Author</th><th>Message</th></tr>')
        for sha, date, author, subject in env['commits']:
            history.append(f'<tr><td>{rev(sha)}</td><td>{e(date[:16])}</td><td>{e(author)}</td><td>{e(subject)}</td></tr>')
        history.append('</table>')
        panels.append(f'''
        <section class="panel" id="{env["name"]}">
          {head}
          <nav class="tabs"><a data-tab="history" class="on">History</a><a data-tab="backups">Backups</a><a data-tab="monitor">Monitor</a><a data-tab="logs">Logs</a></nav>
          <div class="tab on" data-tab="history">{"".join(history)}</div>
          <div class="tab" data-tab="backups">{backups_html}</div>
          <div class="tab" data-tab="monitor">{monitor_html}</div>
          <div class="tab" data-tab="logs">{logs_html}</div>
        </section>''')
    for name, sha in dev_branches:
        run = runs.get(name, {})
        colour, title = ci_light(run)
        see_run = f'<span><a href="{e(run["url"])}">see run</a></span>' if run else ''
        panels.append(f'''
        <section class="panel" id="branch:{e(name)}">
          <div class="head"><h2>{e(name)}</h2><span class="st">{light(colour, title)} tests: {e(title)}</span>
          <span class="acts">{button('deploy-dev', "Deploy to dev", '', name)}{button('promote-staging', "Promote → staging", 'danger', name)}<a class="btn connect" href="https://github.com/{REPO}/tree/{e(name)}">GitHub</a></span></div>
          <div class="facts"><span>revision {rev(sha)}</span><span>last test run {stamp(run.get("when"), True) if run else "—"}</span>
          {see_run}</div>
          <p><small>A development branch is built and tested on GitHub; it is deployed to the dev environment with <code>deploy.sh dev &lt;branch&gt;</code>, then fast-forwarded to staging when green.</small></p>
        </section>''')

    now = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300"><title>Elimelec Odoo</title>
<style>
:root {{ --side:#2b2f3a; --side2:#232732; --top:#1e2129; --ink:#e8eaf0; --page:#f4f5f8; --card:#fff; --text:#1d2433; --muted:#6b7280; --line:#e3e6ec; --accent:#00a09d; --purple:#714b67; }}
* {{ box-sizing:border-box }} body {{ margin:0; font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; color:var(--text); background:var(--page); }}
.top {{ height:44px; background:var(--top); color:var(--ink); display:flex; align-items:center; padding:0 16px; gap:24px; position:sticky; top:0; z-index:2 }}
.top .logo {{ font-weight:700; letter-spacing:.02em }} .top .logo b {{ color:var(--accent) }} .top nav a {{ color:#c9ccd6; margin-right:18px; text-decoration:none }} .top .right {{ margin-left:auto; color:#c9ccd6 }}
.wrap {{ display:flex; min-height:calc(100vh - 44px) }}
aside {{ width:232px; background:var(--side); color:var(--ink); padding:10px 0; flex:none }}
aside .group {{ color:#aeb3c0; font-size:13px; padding:14px 14px 6px; }}
aside .branch {{ display:flex; align-items:center; gap:8px; padding:8px 14px; color:var(--ink); text-decoration:none; font-size:13.5px }}
aside .branch:hover, aside .branch.on {{ background:var(--side2) }} aside .branch.on .bn {{ font-weight:700 }}
aside .bn {{ flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap }} aside .bv {{ color:#aeb3c0; font-size:12px }}
.light {{ display:inline-block; width:9px; height:9px; border-radius:50%; background:#8a8f9c; vertical-align:middle }}
.light.green {{ background:#2ecc71 }} .light.red {{ background:#e74c3c }} .light.orange {{ background:#f39c12 }} .light.grey {{ background:#8a8f9c }}
main {{ flex:1; min-width:0 }}
.panel {{ display:none }} .panel.on {{ display:block }}
.head {{ background:var(--side2); color:var(--ink); padding:14px 24px; display:flex; align-items:center; gap:18px; flex-wrap:wrap }}
.head h2 {{ margin:0; font-size:20px; font-weight:600 }} .head .st {{ color:#c9ccd6 }}
.head .acts {{ margin-left:auto; display:flex; gap:8px; align-items:center; flex-wrap:wrap }} .act {{ margin:0 }}
.btn {{ display:inline-block; padding:7px 14px; border-radius:4px; border:1px solid #4a5060; background:#363b48; color:#e8eaf0; font-size:13px; cursor:pointer; text-decoration:none; font-family:inherit }}
.btn:hover {{ background:#434958 }} .btn.connect {{ background:var(--accent); border-color:var(--accent); color:#fff; font-weight:600 }} .btn.danger {{ border-color:#c0392b; color:#ffb4ad }}
.facts {{ background:#f0f1f5; border-bottom:1px solid var(--line); padding:8px 24px; display:flex; gap:22px; flex-wrap:wrap; color:var(--muted); font-size:13px }}
.tabs {{ background:#fff; border-bottom:1px solid var(--line); padding:0 24px; display:flex; gap:28px }}
.tabs a {{ display:block; padding:14px 0; text-transform:uppercase; font-size:12.5px; letter-spacing:.06em; color:var(--muted); cursor:pointer; border-bottom:3px solid transparent }}
.tabs a.on {{ color:var(--accent); border-color:var(--accent) }}
.tab {{ display:none; padding:20px 24px }} .tab.on {{ display:block }}
table {{ width:100%; border-collapse:collapse; background:var(--card); margin-bottom:18px }} th, td {{ text-align:left; padding:9px 10px; border-bottom:1px solid var(--line); vertical-align:top; font-size:13.5px }} th {{ color:var(--muted); font-weight:600 }}
.jobs {{ max-width:900px }} .tag {{ background:#e8f3ff; color:#1a56a6; border-radius:4px; padding:2px 8px; font-size:12px }}
code {{ font-family:ui-monospace,Menlo,Consolas,monospace; font-size:12.5px; color:var(--purple) }} small {{ color:var(--muted) }}
h4 {{ margin:6px 0 8px; font-size:13px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em }}
dl {{ display:grid; grid-template-columns:auto 1fr; gap:6px 14px; margin:0 0 18px }} dt {{ color:var(--muted) }} dd {{ margin:0 }}
pre {{ background:#1e2129; color:#d6d9e0; padding:12px; border-radius:6px; font-size:12px; overflow:auto; max-height:320px }}
.bar {{ padding:10px 12px; background:#fff; border:1px solid var(--line); border-radius:6px; margin-bottom:14px; color:var(--muted) }}
@media (max-width: 760px) {{ .wrap {{ flex-direction:column }} aside {{ width:auto }} }}
</style></head>
<body>
<div class="top"><span class="logo">elimelec<b>odoo</b></span><nav><a href="#prod">Branches</a><a href="https://github.com/{REPO}/actions">Builds</a><a href="https://github.com/{REPO}">Code</a></nav><span class="right">{e(mon["host"])} · refreshed {now} · every 5 min</span></div>
<div class="wrap">
<aside>{"".join(side)}</aside>
<main>{"".join(panels)}</main>
</div>
<script>
(function () {{
  var links = document.querySelectorAll('aside .branch');
  function show(key) {{
    document.querySelectorAll('.panel').forEach(function (p) {{ p.classList.toggle('on', p.id === key); }});
    links.forEach(function (l) {{ l.classList.toggle('on', l.dataset.target === key); }});
  }}
  links.forEach(function (l) {{ l.addEventListener('click', function (ev) {{ ev.preventDefault(); location.hash = l.dataset.target; show(l.dataset.target); }}); }});
  document.querySelectorAll('.tabs a').forEach(function (t) {{ t.addEventListener('click', function () {{
    var panel = t.closest('.panel');
    panel.querySelectorAll('.tabs a').forEach(function (x) {{ x.classList.toggle('on', x === t); }});
    panel.querySelectorAll('.tab').forEach(function (x) {{ x.classList.toggle('on', x.dataset.tab === t.dataset.tab); }});
  }}); }});
  var key = decodeURIComponent(location.hash.slice(1));
  show(document.getElementById(key) ? key : 'prod');
}})();
</script>
</body></html>'''


def main():
    envs = [environment(*spec) for spec in ENVS]
    branches, runs, by_sha = github()
    page = render(envs, branches, runs, by_sha, backup_rows(), monitor(), logs())
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as handle:
        handle.write(page)
    os.replace(tmp, OUT)


if __name__ == '__main__':
    main()
