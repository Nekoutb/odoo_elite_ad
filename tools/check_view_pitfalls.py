"""Fail on the Odoo 19 view mistakes that only surface at install time.

Well-formed XML naming something Odoo no longer has, or doing something Odoo
now refuses, passes every syntax check and then kills the module load. Each
check below exists because it has already cost this repository a CI cycle.

Usage: python tools/check_view_pitfalls.py addons/elite_clearance [...]
"""
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

# Field names Odoo 19 renamed. old -> (what it is now, where it applies)
RENAMED = {
    'groups_id': ("group_ids", "ir.ui.view, res.users, ir.ui.menu, ir.actions.*"),
    'attrs': ("invisible / readonly / required expressions", "any view element"),
    'states': ("invisible / readonly expressions", "any view element"),
}

# `<field name="x">` inside a data record. The `groups="..."` ATTRIBUTE on a
# view element is a different thing and is correct.
FIELD_RE = re.compile(r'<field\s[^>]*\bname="([^"]+)"')

# ir.actions.act_window.target lost 'inline' in 19.0.
VALID_TARGETS = {'current', 'new', 'fullscreen', 'main'}


def _records(path):
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return []                      # the well-formedness check owns this
    return root.iter('record')


def check_renamed(path, text, problems):
    for lineno, line in enumerate(text.splitlines(), 1):
        for name in FIELD_RE.findall(line):
            if name in RENAMED:
                now, where = RENAMED[name]
                problems.append(
                    '%s:%d: <field name="%s"> was renamed in Odoo 19 — use %s (%s)'
                    % (path, lineno, name, now, where))


def check_inherited_view_groups(path, text, problems):
    """Odoo 19: "Inherited view cannot have 'groups' defined on the record.
    Use 'groups' attributes inside the view definition"."""
    for record in _records(path):
        if record.get('model') != 'ir.ui.view':
            continue
        names = {f.get('name') for f in record.findall('field')}
        if 'inherit_id' in names and ('group_ids' in names or 'groups_id' in names):
            problems.append(
                '%s: view %r inherits AND sets groups on the record. Odoo 19 '
                'refuses this — put groups="..." on the element inside the '
                'arch instead.' % (path, record.get('id')))


def check_action_targets(path, text, problems):
    for record in _records(path):
        if record.get('model') != 'ir.actions.act_window':
            continue
        for field in record.findall('field'):
            if field.get('name') == 'target':
                target = (field.text or '').strip()
                if target and target not in VALID_TARGETS:
                    problems.append(
                        '%s: action %r has target=%r. Odoo 19 allows only %s; '
                        "'inline' was removed and is a hard install failure."
                        % (path, record.get('id'), target,
                           ' / '.join(sorted(VALID_TARGETS))))


CHECKS = (check_renamed, check_inherited_view_groups, check_action_targets)


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
            for check in CHECKS:
                check(path, text, problems)
    for problem in problems:
        print(problem)
    if problems:
        print("\n%d problem(s) that would fail at install." % len(problems))
        return 1
    print("%d XML files scanned, no known install-time pitfalls" % scanned)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
