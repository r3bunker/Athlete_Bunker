#!/usr/bin/env python3
"""Bulk-import a folder of Garmin activity files into Athlete Bunker.

Usage:
    python scripts/import_folder.py PATH [PATH ...]

Each PATH can be a directory (scanned recursively) or a single file.
Supported: .fit, .fit.gz, .tcx, .gpx (also .zip archives containing them).
Duplicates already in the database are skipped, so re-running is safe.
"""
import argparse
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bunker import create_app
from bunker.db import get_db, get_settings
from bunker.ingest import ingest_upload

EXTENSIONS = {".fit", ".tcx", ".gpx"}


def is_activity_file(path):
    name = path.name.lower()
    return (path.suffix.lower() in EXTENSIONS
            or name.endswith(".fit.gz") or name.endswith(".tcx.gz")
            or name.endswith(".gpx.gz"))


def collect_files(paths):
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            yield from sorted(f for f in p.rglob("*") if f.is_file() and is_activity_file(f))
            yield from sorted(f for f in p.rglob("*.zip") if f.is_file())
        elif p.is_file():
            yield p
        else:
            print(f"!  {raw}: not found", file=sys.stderr)


def ingest_one(db, settings, filename, data, counts):
    for r in ingest_upload(db, filename, data, settings):
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        if r["status"] == "ok":
            tss = f" · {round(r['tss'])} TSS" if r.get("tss") else ""
            print(f"✓  {filename}: {r['date']} {r['name']}{tss}")
        elif r["status"] == "duplicate":
            print(f"↺  {filename}: already imported")
        else:
            print(f"✗  {filename}: {r['message']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="folders or files to import")
    args = parser.parse_args()

    app = create_app()
    counts = {}
    with app.app_context():
        db = get_db()
        settings = get_settings(db)
        for path in collect_files(args.paths):
            if path.suffix.lower() == ".zip":
                try:
                    with zipfile.ZipFile(path) as zf:
                        for member in zf.namelist():
                            if is_activity_file(Path(member)):
                                ingest_one(db, settings, f"{path.name}/{Path(member).name}",
                                           zf.read(member), counts)
                except zipfile.BadZipFile:
                    print(f"✗  {path}: not a valid zip", file=sys.stderr)
                continue
            ingest_one(db, settings, path.name, path.read_bytes(), counts)

    total = sum(counts.values())
    print(f"\nDone: {counts.get('ok', 0)} imported, {counts.get('duplicate', 0)} duplicates, "
          f"{counts.get('error', 0)} errors ({total} sessions total)")


if __name__ == "__main__":
    main()
