from __future__ import annotations

import csv
import subprocess
import sys
from collections import defaultdict
from io import StringIO
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
OUTPUT_DIR = ROOT_DIR / "_live_docs" / "postgresql_schemas"

sys.path.insert(0, str(BACKEND_DIR))

import config  # noqa: E402


def run_psql_csv(sql: str) -> list[dict[str, str]]:
    result = subprocess.run(
        [
            "docker",
            "exec",
            config.POSTGRES_CONTAINER_NAME,
            "psql",
            "-U",
            config.POSTGRES_USER,
            "-d",
            config.POSTGRES_DB,
            "--csv",
            "-c",
            sql,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(detail or "Failed to query PostgreSQL schema.")
    return list(csv.DictReader(StringIO(result.stdout)))


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    rows = run_psql_csv(
        """
        SELECT
            c.table_schema,
            c.table_name,
            c.column_name,
            c.data_type,
            c.is_nullable,
            c.column_default,
            c.ordinal_position,
            CASE WHEN tc.constraint_type = 'PRIMARY KEY' THEN 'YES' ELSE 'NO' END AS is_primary_key
        FROM information_schema.columns c
        LEFT JOIN information_schema.key_column_usage kcu
            ON c.table_schema = kcu.table_schema
            AND c.table_name = kcu.table_name
            AND c.column_name = kcu.column_name
        LEFT JOIN information_schema.table_constraints tc
            ON kcu.constraint_schema = tc.constraint_schema
            AND kcu.constraint_name = tc.constraint_name
            AND tc.constraint_type = 'PRIMARY KEY'
        WHERE c.table_schema NOT IN ('information_schema', 'pg_catalog')
        ORDER BY c.table_schema, c.table_name, c.ordinal_position;
        """
    )

    tables: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        tables[(row["table_schema"], row["table_name"])].append(row)

    if not tables:
        print("No user tables found.")
    else:
        for table_key in sorted(tables):
            table_name = table_key[1]
            output_path = OUTPUT_DIR / f"{table_name}.csv"
            with output_path.open("w", encoding="utf-8", newline="") as output_file:
                writer = csv.DictWriter(
                    output_file,
                    fieldnames=[
                        "column_name",
                        "data_type",
                        "is_nullable",
                        "column_default",
                        "is_primary_key",
                    ],
                )
                writer.writeheader()
                for column in tables[table_key]:
                    writer.writerow(
                        {
                            "column_name": column["column_name"],
                            "data_type": column["data_type"],
                            "is_nullable": column["is_nullable"],
                            "column_default": (column["column_default"] or "").replace("\n", " "),
                            "is_primary_key": column["is_primary_key"],
                        }
                    )
            print(f"Updated {output_path.relative_to(ROOT_DIR)}")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)
