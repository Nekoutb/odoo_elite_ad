# Deploying to Odoo.sh

Target: a fresh Odoo.sh project on **19.0**, Enterprise subscription
M260529302698425, Custom plan. The old Odoo Online database (`elite-advisors`,
saas~19.3) holds no data and is being allowed to lapse — never build against
19.3 minor APIs.

## How Odoo.sh reads this repository

Odoo.sh detects addons folders from the manifest files it finds, so
`addons/elite_clearance/__manifest__.py` is picked up as-is: the module does
**not** need to be moved to the repository root. Python dependencies, if any
are ever added, go in a `requirements.txt` beside the addons folder.

## Branches

Odoo.sh maps each Git branch to a stage. The Odoo version is a per-branch
setting in the project, not something derived from the branch name.

| Branch | Stage | Purpose |
|---|---|---|
| `19.0` | Production | What the business runs on. Only ever fast-forwarded from `staging`. |
| `staging` | Staging | Neutralised copy of production data; where an upgrade is rehearsed against real records before it touches production. |
| `dev/<topic>` | Development | Empty or demo database per feature. Cheap to throw away. |

Today the repository has a single `main` branch with one commit. Before the
first deployment:

1. Create `19.0` from `main` and make it the production branch in the
   Odoo.sh project.
2. Create `staging` from `19.0`.
3. Work on `dev/<topic>` branches, merge to `staging`, rehearse, then merge
   to `19.0`.

CI (`.github/workflows/tests.yml`) runs the suite on all of these.

## Order of installation on a production database

1. **`l10n_cm` (SYSCOHADA) first.** The chart of accounts must exist before
   `elite_clearance`, because the module's settings point at real accounts
   and the billing flow refuses to run without them.
2. `elite_clearance`.
3. Configure *Settings → Clearance*: out-of-pocket account, employee advances
   account, fee income account, miscellaneous journal, and optionally the
   sales journal and the four approver lists.
4. Create the settlement journals (Cash, Bank, Mobile Money, Maviance) as
   `cash`/`bank` journals.

Installing runs the post-install hook, which seeds the real master data
(document types, the IM/BO/ES/AI service types with their checklists, and the
expense categories). The hook is idempotent and matches on `code`, so it is
safe to re-run; an `end-` migration script re-runs it after every upgrade so
that new master data reaches existing databases without manual keying.

## Upgrades

- Bump `version` in `__manifest__.py` on every schema change.
- Put upgrade scripts under `migrations/<new version>/` as `pre-`, `post-`
  or `end-` prefixed files.
- Push to `staging` first. Odoo.sh rebuilds on a copy of production data;
  read the build log before promoting.

## Still to do before go-live

- [ ] Create the `19.0` / `staging` / `dev` branches and point the Odoo.sh
      project at them.
- [ ] Verify `l10n_cm` on 19.0 and load it before the module.
- [ ] Import the partner list (CSV) from the old Online database.
- [ ] Decide on OCA `account_financial_report` if Trial Balance / P&L are
      wanted beyond what Enterprise ships.
- [ ] Add a French (`fr_CM`) translation — the module ships English source
      strings with French domain terms in the master data.
