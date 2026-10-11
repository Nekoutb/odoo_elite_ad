#!/usr/bin/env bash
# Deploy the clearance module to one environment on this server.
#   deploy.sh staging            pull the env's branch, upgrade, restart
#   deploy.sh staging <branch>   switch the env's clone to <branch> first
# Replaces the Odoo.sh "push to branch" step. Production is deployed only
# on the owner's word, and only ever from the prod branch.
set -euo pipefail
env_name=${1:?usage: deploy.sh <prod|staging|dev> [branch]}
branch=${2:-}
dir=/opt/elimelec/$env_name
db=$(sed -n 's/^db_name = //p' $dir/odoo.conf)
cd $dir/repo
if [ -n "$branch" ]; then git fetch -q origin "$branch" && git checkout -q "$branch"; fi
cur=$(git rev-parse --abbrev-ref HEAD)
if [ "$env_name" = prod ] && [ "$cur" != prod ]; then echo "refusing: production deploys from the prod branch only (clone is on $cur)"; exit 2; fi
before=$(git rev-parse --short HEAD)
git pull -q --ff-only origin "$cur"
after=$(git rev-parse --short HEAD)
echo "$env_name: branch $cur, $before -> $after"
cd $dir
docker compose stop odoo < /dev/null > /dev/null 2>&1 || true
docker compose run --rm -T odoo odoo -c /etc/odoo/odoo.conf -d "$db" -i elite_finance -u elite_clearance,elite_finance --no-http --stop-after-init < /dev/null > /tmp/deploy_$env_name.log 2>&1 \
  && echo "upgrade: ok, $(grep -cE ' (ERROR|CRITICAL) ' /tmp/deploy_$env_name.log) error lines" \
  || { echo "upgrade: FAILED - see /tmp/deploy_$env_name.log"; grep -E ' (ERROR|CRITICAL) ' /tmp/deploy_$env_name.log | tail -5; }
docker compose up -d < /dev/null > /dev/null 2>&1
sleep 5
docker ps --format "{{.Names}}\t{{.Status}}" | grep "^$env_name-odoo"
docker compose exec -T db psql -U odoo -d "$db" -Atc "SELECT 'elite_clearance ' || latest_version FROM ir_module_module WHERE name='elite_clearance';" < /dev/null
# the overview page reads this line, one per deploy
mkdir -p /opt/elimelec/backups/log
echo "$(date -Is)|$env_name|$cur $before->$after|$( [ -s /tmp/deploy_$env_name.log ] && grep -qE ' (ERROR|CRITICAL) ' /tmp/deploy_$env_name.log && echo 'upgrade with errors' || echo ok )" >> /opt/elimelec/backups/log/deploys.log
[ -x /opt/elimelec/bin/status-page.py ] && /opt/elimelec/bin/status-page.py || true
