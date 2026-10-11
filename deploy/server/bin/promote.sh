#!/usr/bin/env bash
# promote.sh <source-branch> <staging|prod>
#
# The push that Odoo.sh's drag-and-drop did: fast-forward the target
# branch on GitHub to the source branch, then deploy the matching
# environment. Refused unless the source's last test run is green, and
# production is promoted from staging only. Pushes with the server's
# deploy key (/root/.ssh/elimelec_deploy, write access on the repository).
set -euo pipefail
src=${1:?usage: promote.sh <source-branch> <staging|prod>}
target=${2:?usage: promote.sh <source-branch> <staging|prod>}
REPO=Nekoutb/odoo_elite_ad
CONTROL=/opt/elimelec/control/repo
case $target in
    staging) ;;
    prod) [ "$src" = staging ] || { echo "refused: production is promoted from staging only"; exit 2; } ;;
    *) echo "refused: target must be staging or prod"; exit 2 ;;
esac
cd "$CONTROL"
git fetch -q origin
git rev-parse -q --verify "origin/$src" > /dev/null || { echo "refused: no branch $src on GitHub"; exit 2; }
sha=$(git rev-parse "origin/$src")
state=$(python3 - "$REPO" "$sha" <<'PY'
import json, sys, urllib.request
repo, sha = sys.argv[1:]
req = urllib.request.Request(f'https://api.github.com/repos/{repo}/actions/runs?head_sha={sha}&per_page=1',
                             headers={'User-Agent': 'elimelec-promote'})
try:
    runs = json.load(urllib.request.urlopen(req, timeout=15)).get('workflow_runs') or []
    print((runs[0].get('conclusion') or runs[0].get('status')) if runs else 'no run')
except Exception as exc:  # noqa: BLE001
    print(f'unreachable ({exc})')
PY
)
echo "$src is at ${sha:0:7}; tests: $state"
[ "$state" = success ] || { echo "refused: the tests on $src are not green"; exit 3; }
if git merge-base --is-ancestor "origin/$target" "$sha"; then
    git push -q origin "$sha:refs/heads/$target"
    echo "pushed ${sha:0:7} -> $target (fast-forward)"
else
    echo "refused: $target has commits that $src does not; not a fast-forward"; exit 4
fi
exec /opt/elimelec/bin/deploy.sh "$target"
