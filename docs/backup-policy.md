# Backup and storage policy — Elimelec's Odoo

Written 11/10/2026 for the self-hosted server (`docs/deployment-server.md`).
Implemented by the scripts in `deploy/server/bin/`, installed at
`/opt/elimelec/bin/` on the server, and scheduled by
`deploy/server/cron/elimelec-backups`.

## 1. What is protected, and from what

| Asset | Where it lives | Size today, growth |
|---|---|---|
| The database: files, disbursements, entries, invoices, settings, users | Postgres volume of the production stack | 64 MB; about 300 MB a year |
| The filestore: every scanned document, voucher and PDF | Docker volume `elimelec-prod_data`, `filestore/elimelec` | under 1 GB; 10–15 GB a year |
| The server's shape: Caddy, compose files, scripts | `/opt/elimelec` | kilobytes |
| The code | GitHub, `Nekoutb/odoo_elite_ad` | already off-site |

Threats, in the order they happen in real life: a user's mistake (a file
deleted, a wrong import), a bad deployment, a disk or server failure, the
provider losing the machine, a ransomware intrusion, and the legal duty to
produce accounting records years later. One copy on one server covers none
of them, so the rule is **three copies, two media, one off-site**:

1. the live data on the server's NVMe;
2. a local backup folder on the same server, for restores in minutes;
3. an off-site copy in Wasabi object storage, with the bucket's object lock
   so that nothing can be deleted before its time, not even by the server.

Vultr's automatic daily image of the whole machine is a fourth safety net
for the server itself.

## 2. Objectives

| Objective | Target | How |
|---|---|---|
| RPO, records (how much keyed work can be lost) | 1 hour in working hours | Hourly database dump, Monday–Saturday 07:00–20:00 |
| RPO, documents | 24 hours | Nightly filestore mirror; a scan keyed today and deleted tonight is the one loss |
| RTO, same server | under 30 minutes | `restore.sh <env> latest` from the local set |
| RTO, new server | under 3 hours | Rebuild from `docs/deployment-server.md`, `restore.sh prod latest --remote` |
| Retention | 10 years for year-end sets | See §4; OHADA keeps books ten years |
| Proof | weekly | `restore-test.sh --remote` restores the latest set and checks it |

## 3. What is taken, and when (Douala time)

| Job | When | Content | Kept here | Kept off-site |
|---|---|---|---|---|
| hourly | 07:00–20:00, Mon–Sat | `db.dump` (Postgres custom format) | 48 hours | 31 days |
| daily | 02:00 every day | `db.dump`, `manifest.json`, `SHA256SUMS` | 7 sets | 40 days |
| weekly | the Sunday daily | + `filestore.tar.zst`, the whole filestore | with the daily | 12 weeks |
| monthly | the 1st's daily | same | with the daily | 24 months |
| yearly | 1 January's daily | same | with the daily | 10 years |
| mirror | after each daily | the filestore, file by file, to `filestore-mirror/` | — | current, deleted files 30 days |
| server | after each daily | `server/config-<date>.tgz` | — | with the dailies |

Why the mirror: Odoo names a stored file by the hash of its content, so a
file never changes, it is only added or removed. A nightly `rclone sync`
therefore moves only the new documents, and the bucket's versioning keeps
a removed one for the lock period. A daily set plus the mirror rebuilds
that day; the weekly and monthly archives rebuild it from one folder.

Why the database is dumped and not copied: a dump is consistent at one
instant, restores onto any Postgres 16, and is what the restore test
reads back.

## 4. Where it goes: the Wasabi bucket

| Setting | Value | Why |
|---|---|---|
| Bucket | `elimelec-odoo-backups`, one bucket, nothing else in it | A key scoped to one bucket |
| Region | `eu-central-2` (Frankfurt) or `eu-west-2` (Paris) | Same side of the cables as the server |
| Object lock | On, **compliance** mode, default retention **30 days** | A compromised server, or a wrong command, cannot delete the last month |
| Versioning | On (object lock requires it) | The mirror keeps deleted documents |
| Access key | A sub-user allowed only this bucket | Not the root account's key |
| Encryption | Wasabi's at rest, TLS in transit | No client-side key to lose |

Layout in the bucket:

```
prod/daily/YYYY-MM-DD/   db.dump  manifest.json  SHA256SUMS  [filestore.tar.zst]
prod/hourly/YYYY-MM-DD_HHMM/db.dump
prod/filestore-mirror/   the filestore, as on the server
server/config-YYYY-MM-DD.tgz
legacy/                  the final Odoo.sh backup and the Teese export, kept for good
```

Cost: Wasabi bills a minimum of 1 TB a month. Year one uses about 50 GB;
year five about 400 GB with every archive counted. Deleted objects are
billed for 90 days, which the hourly dumps' short life accepts.

## 5. Retention in one sentence

Hourly dumps live 31 days; a daily set lives 40 days, a Sunday's 12 weeks,
a 1st-of-the-month's 24 months, a 1 January's 10 years; the filestore
mirror is current with 30 days of grace for deletions; the local folder
keeps the last 7 daily sets and 48 hours of hourly dumps.

## 6. Restoring

| Situation | Command on the server |
|---|---|
| Refresh staging from last night's production | `restore.sh staging latest` then `deploy.sh staging` |
| A user deleted something this morning | `restore.sh dev latest` (or an hourly dump into dev by hand), read the record back, re-key it |
| Production database damaged, server fine | `restore.sh prod latest` (asks for the database name), then `deploy.sh prod` |
| Production as it was on a date | `restore.sh prod YYYY-MM-DD --remote` |
| Server lost | New server per `docs/deployment-server.md`, then `restore.sh prod latest --remote` |

Every restore into staging or dev neutralises the copy: no mail, no
scheduled jobs. A restore into production is typed-confirmed.

## 7. Proof and alarms

- Each run writes `/opt/elimelec/backups/status-<job>.json` and a line in
  `backups/log/backup.log`.
- Every Sunday `restore-test.sh --remote` fetches the latest off-site set,
  restores it into a scratch database on the staging Postgres, compares
  the counts of journal entries and clearance files with the set's own
  manifest, loads Odoo against it and requires zero error lines, then
  drops it.
- With `HEALTHCHECK_URL` and `HEALTHCHECK_RESTORE_URL` set in
  `backup.env` (healthchecks.io, free), each job pings on success and
  `/fail` on error; a missed ping e-mails the owner. Silence is an alarm,
  not a comfort.
- Once a quarter, the owner reads the log and the Wasabi console, and
  restores one archive by hand into dev. Written in the diary, not left
  to memory.

## 8. Who does what

| Role | Owner | Elite Advisors |
|---|---|---|
| Wasabi account, bucket, access key | Yes | — |
| Keys on the server (`rclone config`) | Yes, once | Gives the command |
| Scripts, schedule, restore test | — | Yes |
| Quarterly manual restore | Yes | Assists |
| Decision to restore production | Yes | Executes |

## 9. Storage on the server itself

260 GB NVMe, 12 GB used after installation. At 15 GB of documents a
year plus 7 local daily sets, the disk reaches half in about eight years.
`df -h /` is in the weekly restore-test log line; the threshold to act is
70 %, by attaching a Vultr block volume for the backup folder.
