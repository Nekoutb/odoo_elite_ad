"""Fail if a module's data/demo XML and CSV files drift from its manifest.

The failure mode this catches is silent: a view file that exists in the tree
but is missing from __manifest__.py is simply never loaded, so the feature is
absent in the running database and nothing in the log says why.

Usage: python tools/check_manifest.py addons/elite_clearance
"""
import ast
import pathlib
import sys

# Directories whose contents are loaded by the manifest's data/demo keys.
LOADED_DIRS = ("data", "demo", "security", "views", "wizard", "report")
LOADED_SUFFIXES = (".xml", ".csv")


def declared_files(module: pathlib.Path) -> set[str]:
    manifest = ast.literal_eval((module / "__manifest__.py").read_text("utf-8"))
    return set(manifest.get("data", [])) | set(manifest.get("demo", []))


def present_files(module: pathlib.Path) -> set[str]:
    found = set()
    for directory in LOADED_DIRS:
        for path in sorted((module / directory).rglob("*")):
            if path.suffix in LOADED_SUFFIXES:
                found.add(path.relative_to(module).as_posix())
    return found


def main(argv: list[str]) -> int:
    status = 0
    for arg in argv or ["addons/elite_clearance"]:
        module = pathlib.Path(arg)
        declared, present = declared_files(module), present_files(module)

        for missing in sorted(declared - present):
            print(f"{module}: manifest lists {missing}, which does not exist")
            status = 1
        for orphan in sorted(present - declared):
            print(f"{module}: {orphan} exists but no manifest entry loads it")
            status = 1
        if not status:
            print(f"{module}: {len(declared)} data files, all accounted for")
    return status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
