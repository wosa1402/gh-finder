from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from .extractor import extract_candidates
from .github_api import GitHubAPIError, GitHubClient
from .storage import append_candidates, load_proxy_values, write_verification_results
from .verifier import verify_proxy

DEFAULT_CONFIG = Path("config/queries.json")
DEFAULT_OUTPUT = Path("data/proxies.csv")
DEFAULT_JSONL = Path("data/proxies.jsonl")
DEFAULT_VERIFY_OUTPUT = Path("data/verified.csv")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "handler"):
        parser.print_help()
        return 2

    try:
        return args.handler(args)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except (GitHubAPIError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="github-proxy-scanner",
        description="Search GitHub public code for proxy candidates with API rate-limit handling.",
    )
    subparsers = parser.add_subparsers(dest="command")

    scan = subparsers.add_parser("scan", help="search GitHub and extract proxy candidates")
    scan.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    scan.add_argument("--query", action="append", help="GitHub code search query; can be repeated")
    scan.add_argument("--pages", type=int, help="pages per query")
    scan.add_argument("--per-page", type=int, help="results per GitHub API page")
    scan.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    scan.add_argument("--jsonl", type=Path, default=DEFAULT_JSONL)
    scan.add_argument("--no-jsonl", action="store_true")
    scan.add_argument("--token-env", default="GITHUB_TOKEN")
    scan.add_argument("--min-delay-seconds", type=float)
    scan.add_argument("--max-file-bytes", type=int)
    scan.add_argument("--max-retries", type=int, default=3)
    scan.add_argument("--include-non-public", action="store_true")
    scan.add_argument("--loop", action="store_true")
    scan.add_argument("--interval-seconds", type=int, default=3600)
    scan.add_argument("--dry-run", action="store_true")
    scan.set_defaults(handler=handle_scan)

    verify = subparsers.add_parser("verify", help="explicitly verify HTTP/HTTPS proxy candidates")
    verify.add_argument("--input", type=Path, default=DEFAULT_OUTPUT)
    verify.add_argument("--output", type=Path, default=DEFAULT_VERIFY_OUTPUT)
    verify.add_argument("--check-url", required=True)
    verify.add_argument("--timeout-seconds", type=float, default=8.0)
    verify.add_argument("--limit", type=int)
    verify.set_defaults(handler=handle_verify)

    extract_file = subparsers.add_parser("extract-file", help="extract proxy candidates from a local text file")
    extract_file.add_argument("path", type=Path)
    extract_file.add_argument("--include-non-public", action="store_true")
    extract_file.set_defaults(handler=handle_extract_file)

    web = subparsers.add_parser("web", help="start the local web dashboard")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8787)
    web.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    web.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    web.add_argument("--jsonl", type=Path, default=DEFAULT_JSONL)
    web.add_argument("--verified-output", type=Path, default=DEFAULT_VERIFY_OUTPUT)
    web.set_defaults(handler=handle_web)

    return parser


def handle_scan(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    queries = args.query or list(config.get("queries", []))
    if not queries:
        raise ValueError("No queries configured. Add --query or edit config/queries.json.")

    pages = positive_int(args.pages if args.pages is not None else config.get("pages_per_query", 1), "pages")
    per_page = positive_int(args.per_page if args.per_page is not None else config.get("per_page", 50), "per-page")
    min_delay = positive_float(
        args.min_delay_seconds
        if args.min_delay_seconds is not None
        else config.get("min_delay_seconds", 2.0),
        "min-delay-seconds",
    )
    max_file_bytes = positive_int(
        args.max_file_bytes if args.max_file_bytes is not None else config.get("max_file_bytes", 524288),
        "max-file-bytes",
    )

    if args.dry_run:
        print("Queries:")
        for query in queries:
            print(f"- {query}")
        print(f"pages={pages} per_page={per_page} min_delay_seconds={min_delay}")
        return 0

    token = os.environ.get(args.token_env)
    if not token:
        raise ValueError(f"Set {args.token_env} before scanning GitHub code.")

    while True:
        run_scan_once(
            token=token,
            queries=queries,
            pages=pages,
            per_page=per_page,
            min_delay_seconds=min_delay,
            max_file_bytes=max_file_bytes,
            max_retries=args.max_retries,
            include_non_public=args.include_non_public,
            output=args.output,
            jsonl=None if args.no_jsonl else args.jsonl,
        )

        if not args.loop:
            return 0

        print(f"[scan] sleeping {args.interval_seconds}s", file=sys.stderr)
        time.sleep(args.interval_seconds)


def run_scan_once(
    *,
    token: str,
    queries: list[str],
    pages: int,
    per_page: int,
    min_delay_seconds: float,
    max_file_bytes: int,
    max_retries: int,
    include_non_public: bool,
    output: Path,
    jsonl: Path | None,
) -> None:
    client = GitHubClient(
        token=token,
        min_delay_seconds=min_delay_seconds,
        max_retries=max_retries,
    )
    all_candidates = []

    for query in queries:
        print(f"[scan] query: {query}", file=sys.stderr)
        results = client.search_code(query, pages=pages, per_page=per_page)
        print(f"[scan] files: {len(results)}", file=sys.stderr)

        for result in results:
            try:
                text = client.fetch_file_text(result, max_file_bytes=max_file_bytes)
            except GitHubAPIError as exc:
                print(f"[scan] skip {result.repository}/{result.path}: {exc}", file=sys.stderr)
                continue
            if text is None:
                continue
            found = extract_candidates(
                text,
                source_url=result.html_url,
                repository=result.repository,
                path=result.path,
                include_non_public=include_non_public,
            )
            if found:
                print(f"[scan] {result.repository}/{result.path}: {len(found)}", file=sys.stderr)
                all_candidates.extend(found)

    new_count, total_count = append_candidates(all_candidates, csv_path=output, jsonl_path=jsonl)
    print(f"[scan] extracted={len(all_candidates)} new={new_count} total={total_count}", file=sys.stderr)


def handle_verify(args: argparse.Namespace) -> int:
    values = load_proxy_values(args.input)
    if args.limit is not None:
        values = values[: positive_int(args.limit, "limit")]

    results = []
    for index, value in enumerate(values, start=1):
        print(f"[verify] {index}/{len(values)} {value}", file=sys.stderr)
        results.append(
            verify_proxy(
                value,
                check_url=args.check_url,
                timeout_seconds=args.timeout_seconds,
            )
        )

    count = write_verification_results(results, args.output)
    print(f"[verify] wrote {count} rows to {args.output}", file=sys.stderr)
    return 0


def handle_extract_file(args: argparse.Namespace) -> int:
    text = args.path.read_text(encoding="utf-8", errors="replace")
    candidates = extract_candidates(
        text,
        source_url=str(args.path),
        repository="local",
        path=str(args.path),
        include_non_public=args.include_non_public,
    )
    for candidate in candidates:
        print(candidate.value)
    return 0


def handle_web(args: argparse.Namespace) -> int:
    from .web import serve

    serve(
        host=args.host,
        port=args.port,
        config_path=args.config,
        output_path=args.output,
        jsonl_path=args.jsonl,
        verified_output_path=args.verified_output,
    )
    return 0


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def positive_int(value: Any, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是整数") from exc
    if parsed <= 0:
        raise ValueError(f"{name} 必须大于 0")
    return parsed


def positive_float(value: Any, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是数字") from exc
    if parsed <= 0:
        raise ValueError(f"{name} 必须大于 0")
    return parsed
