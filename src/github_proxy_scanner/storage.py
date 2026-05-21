from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from .models import ProxyCandidate, VerificationResult

PROXY_FIELDS = [
    "value",
    "host",
    "port",
    "scheme",
    "source_url",
    "repository",
    "path",
    "line",
    "discovered_at",
]

VERIFY_FIELDS = ["value", "status", "http_status", "elapsed_ms", "error", "checked_at"]


def load_existing_values(path: Path) -> set[str]:
    if not path.exists():
        return set()

    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return {row["value"] for row in reader if row.get("value")}


def append_candidates(
    candidates: Iterable[ProxyCandidate],
    *,
    csv_path: Path,
    jsonl_path: Path | None,
) -> tuple[int, int]:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if jsonl_path:
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)

    existing = load_existing_values(csv_path)
    new_records: list[dict] = []

    for candidate in candidates:
        if candidate.value in existing:
            continue
        existing.add(candidate.value)
        new_records.append(candidate.to_record())

    if not new_records:
        return 0, len(existing)

    needs_header = not csv_path.exists() or csv_path.stat().st_size == 0
    with csv_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PROXY_FIELDS)
        if needs_header:
            writer.writeheader()
        writer.writerows(new_records)

    if jsonl_path:
        with jsonl_path.open("a", encoding="utf-8") as handle:
            for record in new_records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    return len(new_records), len(existing)


def load_proxy_values(path: Path) -> list[str]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [row["value"] for row in reader if row.get("value")]


def write_verification_results(results: Iterable[VerificationResult], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [result.to_record() for result in results]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=VERIFY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)
