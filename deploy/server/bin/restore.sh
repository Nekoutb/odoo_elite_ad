#!/usr/bin/env bash
# restore.sh <env> <YYYY-MM-DD|latest> [--remote]
#
# Rebuilds the database and filestore of <env> from a daily backup set of
# the backed-up environment (BACKUP_ENV in backup.env): the local set by
# default, the off-site copy with --remote. Into staging or dev this is
# the ordinary refresh, and the copy is neutralised (no mail, no
# scheduled jobs). Into prod it asks for the database name first.
# Afterwards run deploy.sh <env> so the module matches the code.
set -euo pipefail
env_name=${1:?usage: restore.sh <prod|staging|dev> <YYYY-MM-DD|latest> [--remote]}
which=${2:?usage: restore.sh <prod|staging|dev> <YYYY-MM-DD|latest> [--remote]}
source_flag=${3:-}
ENV_FILE=/opt/elimelec/backups/backup.env
[ -f "$ENV_FILE" ] && . "$ENV_FILE"
SRC_ENV=${BACKUP_ENV:-prod}
RCLONE_REMOTE=${RCLONE_REMOTE:-}
dir_env=/opt/elimelec/$env_name
DB=$(sed -n 's/^db_name = //p' "$dir_env/odoo.conf")
SRC_DB=$(sed -n 's/^db_name = //p' "/opt/elimelec/$SRC_ENV/odoo.conf")
ROOT=/opt/elimelec/backups/$SRC_ENV
LOG=/opt/elimelec/backups/log/backup.log
log() { echo "$(date '+%F %T') [restore->$env_name] $*" | tee -a "$LOG"; }

if [ "$source_flag" = --remote ]; then
    [ -n "$RCLONE_REMOTE" ] || { echo "no RCLONE_REMOTE configured"; exit 2; }
    [ "$which" = latest ] && which=$(rclone lsf --dirs-only "$RCLONE_REMOTE/$SRC_ENV/daily" | sort | tail -1 | tr -d /)
    set=/opt/elimelec/backups/restore/$which
    rm -rf "$set"; mkdir -p "$set"
    log "fetching $which from $RCLONE_REMOTE"
    rclone copy -q "$RCLONE_REMOTE/$SRC_ENV/daily/$which" "$set"
    if [ ! -f "$set/filestore.tar.zst" ]; then
        mkdir -p "$set/filestore"
        rclone copy -q --fast-list "$RCLONE_REMOTE/$SRC_ENV/filestore-mirror" "$set/filestore"
    fi
else
    [ "$which" = latest ] && which=$(ls -1 "$ROOT/daily" | sort | tail -1)
    set=$ROOT/daily/$which
fi
[ -f "$set/db.dump" ] || { echo "no db.dump in $set"; exit 2; }
(cd "$set" && sha256sum -c --quiet SHA256SUMS) && log "checksums of $which verified" || log "warning: checksums of $which not verified"

if [ "$env_name" = prod ]; then
    read -r -p "This REPLACES the production database $DB with the set of $which. Type the database name to continue: " answer
    [ "$answer" = "$DB" ] || { echo "aborted"; exit 3; }
fi

cd "$dir_env"
docker compose stop odoo > /dev/null 2>&1 || true
docker compose up -d db > /dev/null 2>&1
sleep 4
docker compose exec -T db psql -U odoo -d postgres -qc "DROP DATABASE IF EXISTS $DB;" < /dev/null
docker compose exec -T db psql -U odoo -d postgres -qc "CREATE DATABASE $DB ENCODING 'UTF8' TEMPLATE template0;" < /dev/null
docker compose exec -T db pg_restore -U odoo -d "$DB" --no-owner --no-privileges < "$set/db.dump" > /tmp/restore_$env_name.log 2>&1 || true
log "database restored ($(grep -c 'ERROR' /tmp/restore_$env_name.log || true) error lines in /tmp/restore_$env_name.log)"

FS=/var/lib/docker/volumes/elimelec-${env_name}_data/_data/filestore
mkdir -p "$FS"
rm -rf "$FS/$DB"
if [ -f "$set/filestore.tar.zst" ]; then
    tmp=$(mktemp -d); zstd -dc "$set/filestore.tar.zst" | tar -C "$tmp" -xf -
    mv "$tmp/$SRC_DB" "$FS/$DB"; rmdir "$tmp"
elif [ -d "$set/filestore" ]; then
    cp -r "$set/filestore" "$FS/$DB"
elif [ -d "/var/lib/docker/volumes/elimelec-${SRC_ENV}_data/_data/filestore/$SRC_DB" ]; then
    # a local daily set without the archive: the live filestore is on this disk
    cp -r "/var/lib/docker/volumes/elimelec-${SRC_ENV}_data/_data/filestore/$SRC_DB" "$FS/$DB"
fi
chown -R 100:101 "$FS"
log "filestore in place: $(find "$FS/$DB" -type f 2> /dev/null | wc -l) files"

if [ "$env_name" != prod ]; then
    docker compose run --rm -T odoo odoo neutralize -c /etc/odoo/odoo.conf -d "$DB" < /dev/null > /dev/null 2>&1 \
        && log "neutralised: no mail, no scheduled jobs" || log "warning: neutralisation did not run"
fi
docker compose up -d > /dev/null 2>&1
log "restored $which into $env_name ($DB); now run deploy.sh $env_name"
