#!/usr/bin/env bash
# restore-test.sh [--remote]
#
# A backup nobody has restored is a hope, not a backup. Every week this
# restores the latest daily set into a scratch database on the STAGING
# Postgres, loads Odoo against it, compares the counts with the set's
# manifest, drops it, and reports. With --remote the set is fetched from
# the off-site copy, which is the one that matters.
set -euo pipefail
ENV_FILE=/opt/elimelec/backups/backup.env
[ -f "$ENV_FILE" ] && . "$ENV_FILE"
SRC_ENV=${BACKUP_ENV:-prod}
RCLONE_REMOTE=${RCLONE_REMOTE:-}
HEALTHCHECK_RESTORE_URL=${HEALTHCHECK_RESTORE_URL:-}
ROOT=/opt/elimelec/backups/$SRC_ENV
LOG=/opt/elimelec/backups/log/backup.log
SCRATCH=elimelec_restoretest
log() { echo "$(date '+%F %T') [restore-test] $*" | tee -a "$LOG"; }
ping_hc() { [ -n "$HEALTHCHECK_RESTORE_URL" ] && curl -fsS -m 10 --retry 3 "$HEALTHCHECK_RESTORE_URL$1" > /dev/null 2>&1 || true; }
fail() { log "FAILED: $*"; ping_hc /fail; exit 1; }
trap 'fail "at line $LINENO"' ERR

if [ "${1:-}" = --remote ] && [ -n "$RCLONE_REMOTE" ]; then
    which=$(rclone lsf --dirs-only "$RCLONE_REMOTE/$SRC_ENV/daily" | sort | tail -1 | tr -d /)
    set=/opt/elimelec/backups/restore/test-$which
    rm -rf "$set"; mkdir -p "$set"
    rclone copy -q "$RCLONE_REMOTE/$SRC_ENV/daily/$which" "$set"
    source_label="off-site"
else
    which=$(ls -1 "$ROOT/daily" | sort | tail -1)
    set=$ROOT/daily/$which
    source_label="local"
fi
[ -f "$set/db.dump" ] || fail "no daily set to test"
(cd "$set" && sha256sum -c --quiet SHA256SUMS)

cd /opt/elimelec/staging
docker compose up -d db > /dev/null 2>&1
docker compose exec -T db psql -U odoo -d postgres -qc "DROP DATABASE IF EXISTS $SCRATCH;" < /dev/null
docker compose exec -T db psql -U odoo -d postgres -qc "CREATE DATABASE $SCRATCH ENCODING 'UTF8' TEMPLATE template0;" < /dev/null
docker compose exec -T db pg_restore -U odoo -d "$SCRATCH" --no-owner --no-privileges < "$set/db.dump" > /tmp/restore_test.log 2>&1 || true

# what the set says it holds, against what came back
expected_moves=$(python3 -c "import json; print(json.load(open('$set/manifest.json'))['moves'])")
expected_files=$(python3 -c "import json; print(json.load(open('$set/manifest.json'))['files'])")
got_moves=$(docker compose exec -T db psql -U odoo -d "$SCRATCH" -Atc "SELECT count(*) FROM account_move;" < /dev/null)
got_files=$(docker compose exec -T db psql -U odoo -d "$SCRATCH" -Atc "SELECT count(*) FROM logistics_file;" < /dev/null)
[ "$expected_moves" = "$got_moves" ] || fail "journal entries: manifest $expected_moves, restored $got_moves"
[ "$expected_files" = "$got_files" ] || fail "clearance files: manifest $expected_files, restored $got_files"

# Odoo must load the restored registry without an error line
docker compose run --rm -T odoo odoo -c /etc/odoo/odoo.conf -d "$SCRATCH" --no-http --stop-after-init < /dev/null > /tmp/restore_test_load.log 2>&1
errors=$(grep -cE ' (ERROR|CRITICAL) ' /tmp/restore_test_load.log || true)
[ "$errors" = 0 ] || fail "$errors error lines loading the restored database (/tmp/restore_test_load.log)"

docker compose exec -T db psql -U odoo -d postgres -qc "DROP DATABASE $SCRATCH;" < /dev/null
[ "$source_label" = off-site ] && rm -rf "$set"
printf '{"set":"%s","source":"%s","finished":"%s","moves":%s,"files":%s,"result":"ok"}\n' \
    "$which" "$source_label" "$(date -Is)" "$got_moves" "$got_files" > /opt/elimelec/backups/status-restore-test.json
ping_hc ""
log "ok: set $which ($source_label) restores, $got_moves journal entries and $got_files files, registry loads clean"
