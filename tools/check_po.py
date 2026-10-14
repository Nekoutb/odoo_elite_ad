"""Static check of the modules' translation files.

Run by the Static checks CI job:
    python tools/check_po.py addons/elite_clearance

Odoo loads `i18n/<lang>.po` at install and upgrade and LOGS A WARNING for
an entry it cannot read - and a warning line is what turns an Odoo.sh
build yellow (08/10/2026). Worse, a translation whose `%(name)s`
placeholders do not match its source raises at the moment the message
is shown, in the user's face. So, for every `.po` under `i18n/`:

- the file parses (balanced quoted strings, msgid/msgstr pairs);
- no entry is `fuzzy` (Odoo would load it as if it were final);
- no (msgctxt, msgid) appears twice;
- a translated entry keeps the source's named placeholders exactly, the
  same count of positional ones, and the same HTML tags (a view term is
  exported with its inline markup, and a `<b>` that is opened and not
  closed breaks the form it sits in).
"""

import collections
import pathlib
import re
import sys

NAMED = re.compile(r'%\((\w+)\)[sdif]')
POSITIONAL = re.compile(r'(?<!%)%(?!\()[sdif]')
TAGS = re.compile(r'<\s*/?\s*([a-zA-Z][\w-]*)')


def unquote(line):
    line = line.strip()
    if not (line.startswith('"') and line.endswith('"')) or len(line) < 2:
        raise ValueError("unbalanced quotes: %r" % line)
    body = line[1:-1]
    return (body.replace('\\"', '"').replace('\\n', '\n')
            .replace('\\t', '\t').replace('\\\\', '\\'))


def parse(path):
    """Yield (lineno, ctxt, msgid, msgstr, flags) per entry, raising on
    a line that is neither a comment, a keyword nor a continuation."""
    entries = []
    cur = None
    key = None

    def flush():
        if cur is not None and cur['msgid'] is not None:
            entries.append(cur)

    for n, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        line = raw.strip()
        if not line:
            flush()
            cur = None
            key = None
            continue
        if line.startswith('#'):
            if cur is None:
                cur = {'line': n, 'ctxt': None, 'msgid': None,
                       'msgstr': None, 'flags': set()}
            if line.startswith('#,'):
                cur['flags'] |= {f.strip() for f in line[2:].split(',')}
            continue
        if cur is None:
            cur = {'line': n, 'ctxt': None, 'msgid': None,
                   'msgstr': None, 'flags': set()}
        for kw, field in (('msgctxt', 'ctxt'), ('msgid', 'msgid'),
                          ('msgstr', 'msgstr')):
            if line.startswith(kw + ' '):
                key = field
                cur[field] = unquote(line[len(kw):])
                break
        else:
            if line.startswith('"'):
                if key is None:
                    raise ValueError("line %d: continuation without a keyword" % n)
                cur[key] += unquote(line)
            else:
                raise ValueError("line %d: cannot read %r" % (n, raw))
    flush()
    return entries


def check(path):
    problems = []
    try:
        entries = parse(path)
    except ValueError as exc:
        return ["%s: %s" % (path, exc)]
    seen = collections.Counter()
    for e in entries:
        if e['msgid'] == '':
            continue                    # the header
        seen[(e['ctxt'], e['msgid'])] += 1
        where = "%s:%d" % (path, e['line'])
        if 'fuzzy' in e['flags']:
            problems.append("%s: fuzzy entry" % where)
        if e['msgstr'] is None:
            problems.append("%s: no msgstr" % where)
            continue
        if not e['msgstr']:
            continue                    # untranslated: the source shows
        src, dst = e['msgid'], e['msgstr']
        if sorted(NAMED.findall(src)) != sorted(NAMED.findall(dst)):
            problems.append("%s: named placeholders differ: %r -> %r"
                            % (where, NAMED.findall(src), NAMED.findall(dst)))
        if len(POSITIONAL.findall(src)) != len(POSITIONAL.findall(dst)):
            problems.append("%s: positional placeholders differ: %r -> %r"
                            % (where, src, dst))
        if sorted(TAGS.findall(src)) != sorted(TAGS.findall(dst)):
            problems.append("%s: HTML tags differ: %r -> %r"
                            % (where, TAGS.findall(src), TAGS.findall(dst)))
        if src.endswith('\n') != dst.endswith('\n'):
            problems.append("%s: trailing newline differs" % where)
    for (ctxt, msgid), count in seen.items():
        if count > 1:
            problems.append("%s: duplicate entry %r (%d times)"
                            % (path, msgid[:60], count))
    return problems


def main(roots):
    problems = []
    files = []
    for root in roots:
        files += sorted(pathlib.Path(root).glob('i18n/*.po'))
    for path in files:
        found = check(path)
        problems += found
        print("%s  %s" % ("BAD" if found else "ok ", path))
    if problems:
        sys.exit("\n".join(problems))
    print("%d translation file(s) checked" % len(files))


if __name__ == '__main__':
    main(sys.argv[1:] or ['addons/elite_clearance'])
