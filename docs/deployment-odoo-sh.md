# Deploying to Odoo.sh

The Odoo.sh project **already exists**: `nekoutb-odoo-elite-ad`, connected to
this repository on 02/09/2026 at 20:56 UTC. Evidence, checkable without
logging in: an active push webhook to `https://www.odoo.sh/paas/webhook/github`
(`gh api repos/Nekoutb/odoo_elite_ad/hooks`) and a read-only deploy key titled
"DO NOT REMOVE - REQUIRED FOR ODOO.SH". Do not create a second project —
check the webhook first.

Target: that Odoo.sh project on **19.0**, Enterprise subscription
<in the Odoo.sh project settings — never in this repository, it is public>, Custom plan. The old Odoo Online database (`elite-advisors`,
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
| `prod` | Production | What the business runs on. GitHub default. Only ever fast-forwarded from `staging`. |
| `staging` | Staging | Neutralised copy of production data; where an upgrade is rehearsed against real records before it touches production. |
| `dev/<topic>` | Development | Empty or demo database per feature. Cheap to throw away. |

**Why the production branch is called `prod` and not `19.0`.** Odoo.sh
allows exactly one production branch per project and binds the stage to the
branch *name*. Once `prod` had been made production in the console, every
route to replace it failed: dragging another branch in is refused ("you can
only have one production branch per project"), dragging `prod` out lands on
a merge dialog, and the console refuses to delete a production branch. The
name was not worth a support ticket or a new project, so on 03/09/2026 the
repository adopted `prod`. `19.0` is a retired duplicate: delete it from the
Odoo.sh console (Development stage), never from GitHub directly.

The flow is: cut `dev/<topic>` from `staging`, merge to `staging`, let
Odoo.sh rebuild it against neutralised production data, read the build log,
then fast-forward `prod`:

```bash
git push origin staging:prod
```

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

## Never delete the production branch on GitHub, and never expect to rename it

Odoo.sh binds the production *stage* to a branch *name*. Deleting that
branch on GitHub does not "move" production anywhere — it strands the stage,
and Odoo.sh refuses every other operation until the branch is restored. The
order is always: change the production branch in the Odoo.sh console first,
confirm the stage change in the branch history, and only then delete the old
branch from Git. This was learnt the hard way on 03/09/2026 with `prod`. The same day taught
the corollary: the production branch cannot be swapped for another from the
console either. Choose the production branch name once, at project creation.

## Upgrades

- Bump `version` in `__manifest__.py` on every schema change.
- Put upgrade scripts under `migrations/<new version>/` as `pre-`, `post-`
  or `end-` prefixed files.
- Push to `staging` first. Odoo.sh rebuilds on a copy of production data;
  read the build log before promoting.

## Still to do before go-live

- [x] Odoo.sh project exists and is connected to this repository.
- [x] Production branch settled: `prod` (see *Branches* above).
- [x] `prod` fast-forwarded to `staging` (v19.0.6.0.0) — the first real
      promotion.
- [ ] Console: drag `staging` from Development into the **Staging** stage,
      so it builds on a copy of production rather than an empty database.
- [ ] Console: delete `19.0` from the Development stage (retired duplicate).
- [ ] Confirm the production branch's Odoo version is 19.0 in its settings.
- [ ] Verify `l10n_cm` on 19.0 and load it before the module.
- [ ] Configure Settings → Clearance on production (421101, 47xx, fee income,
      journals) and create the team users.
- [ ] Import the partner list (CSV) from the old Online database.
- [ ] Decide on OCA `account_financial_report` if Trial Balance / P&L are
      wanted beyond what Enterprise ships.
- [ ] Add a French (`fr_CM`) translation — the module ships English source
      strings with French domain terms in the master data.
