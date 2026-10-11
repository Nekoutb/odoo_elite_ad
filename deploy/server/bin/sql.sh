#!/usr/bin/env bash
# sql.sh <env> <file.sql>   run a SQL file against that environment's database
set -e
cd /opt/elimelec/$1
db=$(sed -n 's/^db_name = //p' odoo.conf)
docker compose exec -T db psql -U odoo -d "$db" -AtF' | ' -f - < "$2"
