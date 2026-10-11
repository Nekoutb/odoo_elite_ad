#!/usr/bin/env bash
# rebuild.sh staging | dev
#
#   staging  the latest backup set restored over it, neutralised, then
#            the modules upgraded to the staging branch (restore + deploy)
#   dev      a fresh database with demo data on dev's current branch
set -euo pipefail
env_name=${1:?usage: rebuild.sh staging|dev}
case $env_name in
    staging)
        /opt/elimelec/bin/restore.sh staging latest
        exec /opt/elimelec/bin/deploy.sh staging ;;
    dev)
        cd /opt/elimelec/dev
        DB=$(sed -n 's/^db_name = //p' odoo.conf)
        docker compose stop odoo > /dev/null 2>&1 || true
        docker compose up -d db > /dev/null 2>&1; sleep 4
        docker compose exec -T db psql -U odoo -d postgres -qc "DROP DATABASE IF EXISTS $DB;" < /dev/null
        rm -rf "/var/lib/docker/volumes/elimelec-dev_data/_data/filestore/$DB"
        echo "dev: installing a fresh demo database on $(git -C repo rev-parse --abbrev-ref HEAD) ($(git -C repo rev-parse --short HEAD))"
        docker compose run --rm -T odoo odoo -c /etc/odoo/odoo.conf -d "$DB" \
            -i elite_clearance,elite_clearance_teese,elite_finance --with-demo --no-http --stop-after-init \
            < /dev/null > /tmp/rebuild_dev.log 2>&1 \
            && echo "install: ok, $(grep -cE ' (ERROR|CRITICAL) ' /tmp/rebuild_dev.log || true) error lines" \
            || { echo "install: FAILED"; grep -E ' (ERROR|CRITICAL) ' /tmp/rebuild_dev.log | tail -5; exit 1; }
        docker compose up -d > /dev/null 2>&1
        echo "dev: up, login admin / admin" ;;
    *) echo "usage: rebuild.sh staging|dev"; exit 2 ;;
esac
