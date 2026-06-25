#!/usr/bin/env python3
"""Export/import Google Chrome custom search engines.

Chrome stores search engine metadata in each profile's `Web Data` SQLite
DB, usually in the `keywords` table. This CLI exports a portable JSON file
and imports it into another Chrome profile.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CORE_COLUMNS = [
    "short_name",
    "keyword",
    "url",
    "favicon_url",
    "safe_for_autoreplace",
    "originating_url",
    "date_created",
    "usage_count",
    "input_encodings",
    "suggest_url",
    "prepopulate_id",
    "created_by_policy",
    "last_modified",
    "sync_guid",
    "alternate_urls",
    "image_url",
    "search_url_post_params",
    "suggest_url_post_params",
    "image_url_post_params",
    "new_tab_url",
    "last_visited",
]


class CseError(RuntimeError):
    """User-facing CLI error."""


def default_web_data_path() -> Path:
    """Return the default Chrome profile Web Data path for this OS."""
    system = platform.system()

    if system == "Darwin":
        return Path.home() / "Library/Application Support/Google/Chrome/Default/Web Data"

    if system == "Windows":
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise CseError("LOCALAPPDATA is not set; pass --db explicitly.")
        return Path(local) / "Google/Chrome/User Data/Default/Web Data"

    return Path.home() / ".config/google-chrome/Default/Web Data"


def connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise CseError(f"Chrome Web Data DB not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def table_columns(conn: sqlite3.Connection, table: str) -> dict[str, dict[str, Any]]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if not rows:
        raise CseError(f"Could not inspect table: {table}")

    return {
        row["name"]: {
            "cid": row["cid"],
            "type": row["type"],
            "notnull": bool(row["notnull"]),
            "default": row["dflt_value"],
            "pk": bool(row["pk"]),
        }
        for row in rows
    }


def parse_sqlite_default(value: Any) -> Any:
    if value is None:
        return None

    raw = str(value).strip()

    if raw.upper() == "NULL":
        return None

    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1].replace("''", "'")

    try:
        return int(raw)
    except ValueError:
        pass

    try:
        return float(raw)
    except ValueError:
        pass

    return raw


def export_keywords(db_path: Path, out_path: Path) -> None:
    with connect(db_path) as conn:
        cols = table_columns(conn, "keywords")
        select_cols = [c for c in CORE_COLUMNS if c in cols]

        for required in ["short_name", "keyword", "url"]:
            if required not in select_cols:
                raise CseError(f"Required column missing from keywords table: {required}")

        query = f"""
            SELECT {", ".join(select_cols)}
            FROM keywords
            WHERE keyword IS NOT NULL
              AND keyword != ''
            ORDER BY lower(keyword)
        """

        rows = [dict(row) for row in conn.execute(query).fetchall()]

    payload = {
        "format": "chrome-keywords-export-v1",
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_db": str(db_path),
        "columns": select_cols,
        "rows": rows,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Exported {len(rows)} search engines to {out_path}")


def backup_db(db_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = db_path.with_name(f"{db_path.name}.backup-{timestamp}")
    shutil.copy2(db_path, backup_path)
    return backup_path


def import_keywords(db_path: Path, in_path: Path, mode: str) -> None:
    if not in_path.exists():
        raise CseError(f"Input file not found: {in_path}")

    payload = json.loads(in_path.read_text(encoding="utf-8"))

    if payload.get("format") != "chrome-keywords-export-v1":
        raise CseError("Input file does not look like a chrome-keywords-export-v1 JSON file.")

    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        raise CseError("Invalid JSON: rows must be a list.")

    conn = connect(db_path)
    cols = table_columns(conn, "keywords")

    for required in ["short_name", "keyword", "url"]:
        if required not in cols:
            raise CseError(f"Required column missing from destination keywords table: {required}")

    backup_path = backup_db(db_path)
    print(f"Backup created: {backup_path}")

    exported_columns = payload.get("columns") or []
    importable_columns = [
        c for c in exported_columns
        if c in cols and not cols[c]["pk"] and c != "id"
    ]

    inserted = 0
    updated = 0
    skipped = 0

    try:
        with conn:
            for row in rows:
                if not isinstance(row, dict):
                    skipped += 1
                    continue

                keyword = row.get("keyword")
                if not keyword:
                    skipped += 1
                    continue

                existing = conn.execute(
                    "SELECT id FROM keywords WHERE keyword = ?",
                    (keyword,),
                ).fetchone()

                if existing and mode == "skip":
                    skipped += 1
                    continue

                data: dict[str, Any] = {}

                for col in importable_columns:
                    if col in row:
                        data[col] = row[col]

                for col, meta in cols.items():
                    if meta["pk"] or col in data:
                        continue

                    if meta["notnull"]:
                        default = parse_sqlite_default(meta["default"])
                        if default is not None:
                            data[col] = default
                        elif col in ("short_name", "keyword", "url"):
                            data[col] = row.get(col, "")
                        elif "INT" in (meta["type"] or "").upper():
                            data[col] = 0
                        else:
                            data[col] = ""

                if not data.get("short_name"):
                    data["short_name"] = keyword
                if not data.get("url"):
                    skipped += 1
                    continue

                if existing:
                    set_cols = [c for c in data.keys() if c != "keyword"]
                    sql = (
                        "UPDATE keywords SET "
                        + ", ".join(f"{c} = ?" for c in set_cols)
                        + " WHERE keyword = ?"
                    )
                    params = [data[c] for c in set_cols] + [keyword]
                    conn.execute(sql, params)
                    updated += 1
                else:
                    columns = list(data.keys())
                    placeholders = ", ".join("?" for _ in columns)
                    sql = f"INSERT INTO keywords ({', '.join(columns)}) VALUES ({placeholders})"
                    conn.execute(sql, [data[c] for c in columns])
                    inserted += 1
    except Exception:
        print("Import failed. Your original DB backup is still here:", file=sys.stderr)
        print(f"  {backup_path}", file=sys.stderr)
        raise
    finally:
        conn.close()

    print(f"Import complete: {inserted} inserted, {updated} updated, {skipped} skipped.")
    print("Restart Chrome and check chrome://settings/searchEngines")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cse",
        description="Export/import Google Chrome custom search engines from the Web Data SQLite DB.",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    exp = sub.add_parser("export", help="Export Chrome search engines to JSON.")
    exp.add_argument("--db", type=Path, default=None, help="Path to Chrome 'Web Data' file.")
    exp.add_argument("--out", type=Path, required=True, help="Output JSON path.")

    imp = sub.add_parser("import", help="Import Chrome search engines from JSON.")
    imp.add_argument("--db", type=Path, default=None, help="Path to Chrome 'Web Data' file.")
    imp.add_argument("--in", dest="infile", type=Path, required=True, help="Input JSON path.")
    imp.add_argument(
        "--mode",
        choices=["update", "skip"],
        default="update",
        help="When a keyword already exists: update it or skip it. Default: update.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    db_path = args.db or default_web_data_path()

    try:
        if args.command == "export":
            export_keywords(db_path, args.out)
        elif args.command == "import":
            import_keywords(db_path, args.infile, args.mode)
        else:
            parser.error(f"Unknown command: {args.command}")
    except CseError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except sqlite3.Error as exc:
        print(f"SQLite error: {exc}", file=sys.stderr)
        print("Tip: close Chrome and try again. For import, make sure you are using the correct profile.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
