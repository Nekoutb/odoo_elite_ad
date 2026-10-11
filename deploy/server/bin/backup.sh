#!/usr/bin/env bash
# backup.sh daily [--full] | hourly
#
# Backups of the Odoo environment named in /opt/elimelec/backups/backup.env
# (BACKUP_ENV, production once cut over). Policy: docs/backup-policy.md.
#
#   hourly  a dump of the database only, kept 48 h here and 31 days off-site
#   daily   a dump of the database, the manifest, and - on Sundays, on the
#           1st, or with --full - an archive of the filestore; kept 7 sets
#           here and 40 daily / 12 weekly / 24 monthly / 10 yearly off-site;
#           then the filestore mirror off-site (every document, once)
#
# Off-site is an rclone remote (Wasabi); with none configured the backup
# is local only and says so. Every run pings HEALTHCHECK_URL if set, and
# /fail on an error, so silence raises an alarm.
set -euo pipefail
ENV_FILE=/opt/elimelec/backups/backup.env
[ -f "$ENV_FILE" ] && . "$ENV_FILE"
RCLONE_REMOTE=${RCLONE_REMOTE:-}
HEALTHCHECK_URL=${HEALTHCHECK_URL:-}
ENV_NAME=${BACKUP_ENV:-prod}
mode=${1:?usage: backup.sh daily [--full] | hourly}
full=${2:-}

dir_env=/opt/elimelec/$ENV_NAME
DB=$(sed -n 's/^db_name = //p' "$dir_env/odoo.conf")
ROOT=/opt/elimelec/backups/$ENV_NAME
LOG=/opt/elimelec/backups/log/backup.log
FILESTORE=/var/lib/docker/volumes/elimelec-${ENV_NAME}_data/_data/filestore/$DB
mkdir -p "$ROOT/daily" "$ROOT/hourly" /opt/elimelec/backups/log

log() { echo "$(date '+%F %T') [$ENV_NAME/$mode] $*" | tee -a "$LOG"; }
ping_hc() { [ -n "$HEALTHCHECK_URL" ] && curl -fsS -m 10 --retry 3 "$HEALTHCHECK_URL$1" > /dev/null 2>&1 || true; }
fail() { log "FAILED: $*"; ping_hc /fail; exit 1; }
trap 'fail "at line $LINENO"' ERR

cd "$dir_env"
docker compose ps --status running db --format '{{.Name}}' | grep -q . || fail "database container of $ENV_NAME is not running"
now=$(date +%Y-%m-%d_%H%M)
today=$(date +%F)

if [ "$mode" = hourly ]; then
    out=$ROOT/hourly/$now
    mkdir -p "$out"
    docker compose exec -T db pg_dump -U odoo -Fc --no-owner "$DB" > "$out/db.dump"
    log "hourly dump $(du -h "$out/db.dump" | cut -f1)"
    find "$ROOT/hourly" -mindepth 1 -maxdepth 1 -type d -mmin +$((48 * 60)) -exec rm -rf {} +
    if [ -n "$RCLONE_REMOTE" ]; then
        rclone copy -q "$out" "$RCLONE_REMOTE/$ENV_NAME/hourly/$now"
        # the bucket's object lock refuses earlier deletions; that is the point
        rclone delete -q --min-age 31d "$RCLONE_REMOTE/$ENV_NAME/hourly" || true
        rclone rmdirs -q --leave-root "$RCLONE_REMOTE/$ENV_NAME/hourly" || true
    fi
else
    out=$ROOT/daily/$today
    rm -rf "$out"
    mkdir -p "$out"
    docker compose exec -T db pg_dump -U odoo -Fc --no-owner "$DB" > "$out/db.dump"
    # weekly (Sunday) and monthly (1st): the whole filestore as one archive,
    # so a point in time can be rebuilt from one folder without the mirror
    dow=$(date +%u); dom=$(date +%d)
    if [ "$dow" = 7 ] || [ "$dom" = 01 ] || [ "$full" = --full ]; then
        [ -d "$FILESTORE" ] && tar -C "$(dirname "$FILESTORE")" -cf - "$(basename "$FILESTORE")" | zstd -q -T0 -3 > "$out/filestore.tar.zst"
    fi
    # the manifest: what this set holds, read back by the restore test
    docker compose exec -T db psql -U odoo -d "$DB" -Atc "
        SELECT json_build_object(
            'db', '$DB', 'environment', '$ENV_NAME', 'taken', now(),
            'commit', '$(git -C "$dir_env/repo" rev-parse --short HEAD 2> /dev/null || echo "")',
            'modules', (SELECT json_object_agg(name, latest_version) FROM ir_module_module WHERE name LIKE 'elite%' AND state = 'installed'),
            'attachments', (SELECT count(*) FROM ir_attachment WHERE store_fname IS NOT NULL),
            'filestore_files', $( [ -d "$FILESTORE" ] && find "$FILESTORE" -type f | wc -l || echo 0 ),
            'moves', (SELECT count(*) FROM account_move),
            'files', (SELECT count(*) FROM logistics_file),
            'expenses', (SELECT count(*) FROM logistics_expense))" < /dev/null > "$out/manifest.json"
    (cd "$out" && sha256sum -- * > SHA256SUMS)
    log "daily set $(du -sh "$out" | cut -f1): $(ls "$out" | tr '\n' ' ')"
    # here: the last 7 sets, for a fast restore
    ls -1d "$ROOT"/daily/*/ | sort | head -n -7 | xargs -r rm -rf
    if [ -n "$RCLONE_REMOTE" ]; then
        rclone copy -q "$out" "$RCLONE_REMOTE/$ENV_NAME/daily/$today"
        rclone check -q "$out" "$RCLONE_REMOTE/$ENV_NAME/daily/$today"
        # every document, once: Odoo names a file by the hash of its content,
        # so the mirror only ever receives new files; a deleted one is kept by
        # the bucket's versioning for the lock period
        [ -d "$FILESTORE" ] && rclone sync -q --fast-list "$FILESTORE" "$RCLONE_REMOTE/$ENV_NAME/filestore-mirror"
        python3 /opt/elimelec/bin/backup-prune.py "$RCLONE_REMOTE/$ENV_NAME/daily" | tee -a "$LOG"
        # the server's own shape (no secrets): enough to rebuild the machine
        tar -C /opt/elimelec -czf /tmp/server-config.tgz caddy/Caddyfile caddy/docker-compose.yml bin \
            prod/docker-compose.yml staging/docker-compose.yml dev/docker-compose.yml 2> /dev/null
        rclone copyto -q /tmp/server-config.tgz "$RCLONE_REMOTE/server/config-$today.tgz"
        rm -f /tmp/server-config.tgz
        log "off-site: $(rclone size "$RCLONE_REMOTE/$ENV_NAME" | tr '\n' ' ')"
    else
        log "no RCLONE_REMOTE configured: local copy only"
    fi
fi
printf '{"environment":"%s","mode":"%s","finished":"%s","set":"%s","remote":"%s"}\n' \
    "$ENV_NAME" "$mode" "$(date -Is)" "$out" "${RCLONE_REMOTE:-none}" > "/opt/elimelec/backups/status-$mode.json"
ping_hc ""
log "ok"
