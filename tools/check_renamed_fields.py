"""Fail on Odoo 19 field names that were renamed and now raise at install.

The static checks catch malformed XML but not a *valid* tag naming a field
that no longer exists — that only shows up when the module is installed, so
it costs a whole CI cycle. These are the renames this repository has already
been bitten by, so they are cheap to guard.

Usage: python tools/check_renamed_fields.py addons/elite_clearance [...]
"""
import pathlib
import re
import sys

# old field name -> (what it is now, where it applies)
RENAMED = {
    'groups_id': ("group_ids", "ir.ui.view, res.users, ir.ui.menu, ir.actions.*"),
    'attrs': ("invisible / readonly / required expressions", "any view element"),
    'states': ("invisible / readonly expressions", "any view element"),
}

# <field name="x"> inside a data record. The `groups="..."` ATTRIBUTE on a
# view element is a different thing and stays as it is.
FIELD_RE = re.compile(r'<field\s[^>]*\bname="([^"]+)"')


def main(argv):
    targets = [pathlib.Path(a) for a in argv] or [pathlib.Path("addons")]
    problems = []
    scanned = 0
    for target in targets:
        paths = [target] if target.is_file() else sorted(target.rglob("*.xml"))
        for path in paths:
            if path.suffix != ".xml":
                continue
            scanned += 1
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), 1):
                for name in FIELD_RE.findall(line):
                    if name in RENAMED:
                        now, where = RENAMED[name]
                        problems.append(
                            "%s:%d: <field name=\"%s\"> was renamed in Odoo 19 "
                            "— use %s (%s)" % (path, lineno, name, now, where))
    for problem in problems:
        print(problem)
    if problems:
        print("\n%d renamed field(s) would fail at install." % len(problems))
        return 1
    print("%d XML files scanned, no renamed fields" % scanned)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
