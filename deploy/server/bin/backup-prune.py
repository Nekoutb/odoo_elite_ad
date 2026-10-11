#!/usr/bin/env python3
"""Off-site retention of the daily sets (docs/backup-policy.md).

    backup-prune.py <remote>/<env>/daily [--dry-run]

Keeps a daily set for 40 days, a Sunday's set for 12 weeks, the 1st of
the month's for 24 months and 1 January's for 10 years; removes the rest.
Forty days rather than thirty so that the bucket's 30-day object lock
has lapsed by the time a set is removed. A set that the lock still
protects is simply reported and tried again another day.
"""

import datetime as dt
import subprocess
import sys

remote = sys.argv[1].rstrip('/')
dry = '--dry-run' in sys.argv
today = dt.date.today()

listing = subprocess.run(['rclone', 'lsf', '--dirs-only', remote],
                         capture_output=True, text=True, check=True).stdout.split()
kept, removed = [], []
for entry in sorted(listing):
    name = entry.strip('/')
    try:
        day = dt.date.fromisoformat(name)
    except ValueError:
        continue
    age = (today - day).days
    keep = (age <= 40
            or (day.isoweekday() == 7 and age <= 7 * 12)
            or (day.day == 1 and age <= 731)
            or (day.month == 1 and day.day == 1 and age <= 3653))
    if keep:
        kept.append(name)
        continue
    if dry:
        removed.append(name)
        continue
    result = subprocess.run(['rclone', 'purge', '-q', f'{remote}/{name}'],
                            capture_output=True, text=True)
    if result.returncode == 0:
        removed.append(name)
    else:
        print(f'prune: {name} still protected or failed: {result.stderr.strip()[:120]}')
print(f'prune: {len(kept)} daily sets kept, {len(removed)} removed'
      + (f' ({", ".join(removed)})' if removed else ''))
