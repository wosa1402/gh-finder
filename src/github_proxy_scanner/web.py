from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import os
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .cli import load_config, positive_float, positive_int
from .extractor import extract_candidates
from .github_api import GitHubAPIError, GitHubClient
from .storage import append_candidates, load_proxy_values, write_verification_results
from .verifier import verify_proxy

ASSET_DIR = Path(__file__).with_name("web_assets")
DEFAULT_CHECK_URL = "http://example.com/"
DEFAULT_VERIFY_LIMIT = 200


@dataclass
class JobState:
    kind: str = "idle"
    running: bool = False
    status: str = "idle"
    started_at: str | None = None
    finished_at: str | None = None
    error: str = ""
    stop_requested: bool = False
    metrics: dict[str, Any] = field(default_factory=dict)


class WebState:
    def __init__(
        self,
        *,
        config_path: Path,
        output_path: Path,
        jsonl_path: Path,
        verified_output_path: Path,
    ) -> None:
        self.config_path = config_path
        self.output_path = output_path
        self.jsonl_path = jsonl_path
        self.verified_output_path = verified_output_path
        self.lock = threading.RLock()
        self.logs: deque[str] = deque(maxlen=500)
        self.job = JobState()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def log(self, message: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {message}"
        with self.lock:
            self.logs.append(line)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "job": {
                    "kind": self.job.kind,
                    "running": self.job.running,
                    "status": self.job.status,
                    "startedAt": self.job.started_at,
                    "finishedAt": self.job.finished_at,
                    "error": self.job.error,
                    "stopRequested": self.job.stop_requested,
                    "metrics": dict(self.job.metrics),
                },
                "logs": list(self.logs),
                "paths": {
                    "output": str(self.output_path),
                    "jsonl": str(self.jsonl_path),
                    "verifiedOutput": str(self.verified_output_path),
                },
            }

    def start_job(self, kind: str, target: Any, args: tuple[Any, ...]) -> None:
        with self.lock:
            if self.job.running:
                raise ValueError("已有任务正在运行。")
            self.stop_event.clear()
            self.job = JobState(
                kind=kind,
                running=True,
                status="running",
                started_at=iso_local_time(),
                metrics={},
            )
            self.thread = threading.Thread(target=target, args=args, daemon=True)
            self.thread.start()

    def finish_job(self, status: str, *, error: str = "") -> None:
        with self.lock:
            self.job.running = False
            self.job.status = status
            self.job.finished_at = iso_local_time()
            self.job.error = error
            self.job.stop_requested = self.stop_event.is_set()

    def update_metrics(self, **metrics: Any) -> None:
        with self.lock:
            self.job.metrics.update(metrics)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="启动本地 GitHub 代理扫描器 Web 控制台。")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--config", type=Path, default=Path("config/queries.json"))
    parser.add_argument("--output", type=Path, default=Path("data/proxies.csv"))
    parser.add_argument("--jsonl", type=Path, default=Path("data/proxies.jsonl"))
    parser.add_argument("--verified-output", type=Path, default=Path("data/verified.csv"))
    args = parser.parse_args(argv)

    serve(
        host=args.host,
        port=args.port,
        config_path=args.config,
        output_path=args.output,
        jsonl_path=args.jsonl,
        verified_output_path=args.verified_output,
    )
    return 0


def serve(
    *,
    host: str,
    port: int,
    config_path: Path,
    output_path: Path,
    jsonl_path: Path,
    verified_output_path: Path,
) -> None:
    state = WebState(
        config_path=config_path,
        output_path=output_path,
        jsonl_path=jsonl_path,
        verified_output_path=verified_output_path,
    )

    class Handler(DashboardHandler):
        app_state = state

    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}"
    state.log(f"控制台已启动：{url}")
    print(f"GitHub 代理扫描器控制台已启动：{url}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("正在停止控制台。", file=sys.stderr)
    finally:
        server.server_close()


class DashboardHandler(BaseHTTPRequestHandler):
    app_state: WebState
    server_version = "GitHubProxyScannerWeb/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_asset("index.html")
            return
        if parsed.path.startswith("/assets/"):
            self.send_asset(parsed.path.removeprefix("/assets/"))
            return
        if parsed.path == "/api/config":
            self.send_json(self.default_config())
            return
        if parsed.path == "/api/status":
            self.send_json(self.app_state.snapshot())
            return
        if parsed.path == "/api/results":
            params = parse_qs(parsed.query)
            limit = parse_limit(params.get("limit", ["200"])[0], default=200)
            self.send_json(read_results(self.app_state.output_path, limit=limit))
            return
        if parsed.path == "/api/verified":
            params = parse_qs(parsed.query)
            limit = parse_limit(params.get("limit", ["200"])[0], default=200)
            self.send_json(read_csv_rows(self.app_state.verified_output_path, limit=limit))
            return
        if parsed.path == "/download/proxies.csv":
            self.send_file(self.app_state.output_path, "text/csv")
            return
        if parsed.path == "/download/verified.csv":
            self.send_file(self.app_state.verified_output_path, "text/csv")
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self.read_json()
            if parsed.path == "/api/scan":
                config = self.build_scan_config(payload)
                self.app_state.start_job("scan", run_scan_job, (self.app_state, config))
                self.send_json({"ok": True, "status": self.app_state.snapshot()})
                return
            if parsed.path == "/api/verify":
                config = self.build_verify_config(payload)
                self.app_state.start_job("verify", run_verify_job, (self.app_state, config))
                self.send_json({"ok": True, "status": self.app_state.snapshot()})
                return
            if parsed.path == "/api/stop":
                self.app_state.stop_event.set()
                with self.app_state.lock:
                    self.app_state.job.stop_requested = True
                self.app_state.log("已请求停止任务")
                self.send_json({"ok": True, "status": self.app_state.snapshot()})
                return
        except (GitHubAPIError, OSError, ValueError) as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def default_config(self) -> dict[str, Any]:
        config = load_config(self.app_state.config_path)
        return {
            "queries": config.get("queries", []),
            "pages": config.get("pages_per_query", 1),
            "perPage": config.get("per_page", 50),
            "minDelaySeconds": config.get("min_delay_seconds", 2.0),
            "maxFileBytes": config.get("max_file_bytes", 524288),
            "tokenEnv": "GITHUB_TOKEN",
            "output": str(self.app_state.output_path),
            "jsonl": str(self.app_state.jsonl_path),
            "verifiedOutput": str(self.app_state.verified_output_path),
            "defaultCheckUrl": DEFAULT_CHECK_URL,
            "defaultVerifyLimit": DEFAULT_VERIFY_LIMIT,
        }

    def build_scan_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        queries = normalize_queries(payload.get("queries"))
        if not queries:
            queries = list(load_config(self.app_state.config_path).get("queries", []))
        if not queries:
            raise ValueError("没有配置搜索词。")

        token_env = str(payload.get("tokenEnv") or "GITHUB_TOKEN")
        token = str(payload.get("token") or os.environ.get(token_env) or "").strip()
        if not token:
            raise ValueError(f"请设置 {token_env}，或在控制台输入 Token。")

        return {
            "token": token,
            "queries": queries,
            "pages": positive_int(payload.get("pages", 1), "页数"),
            "per_page": positive_int(payload.get("perPage", 50), "每页数量"),
            "min_delay_seconds": positive_float(payload.get("minDelaySeconds", 2.0), "请求间隔"),
            "max_file_bytes": positive_int(payload.get("maxFileBytes", 524288), "最大文件字节数"),
            "include_non_public": bool(payload.get("includeNonPublic", False)),
            "max_retries": positive_int(payload.get("maxRetries", 3), "最大重试次数"),
        }

    def build_verify_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        check_url = str(payload.get("checkUrl") or DEFAULT_CHECK_URL).strip()
        if not check_url.startswith(("http://", "https://")):
            raise ValueError("检查 URL 必须以 http:// 或 https:// 开头。")

        limit = payload.get("limit")
        parsed_limit = DEFAULT_VERIFY_LIMIT if limit in (None, "") else positive_int(limit, "验证数量")
        return {
            "check_url": check_url,
            "timeout_seconds": positive_float(payload.get("timeoutSeconds", 8.0), "超时秒数"),
            "limit": parsed_limit,
        }

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        body = self.rfile.read(length)
        return json.loads(body.decode("utf-8"))

    def send_asset(self, name: str) -> None:
        if "/" in name or "\\" in name or name.startswith("."):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        path = ASSET_DIR / name
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type = f"{content_type}; charset=utf-8"
        self.send_bytes(path.read_bytes(), content_type=content_type)

    def send_file(self, path: Path, content_type: str) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_bytes(path.read_bytes(), content_type=content_type)

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_bytes(self, data: bytes, *, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run_scan_job(state: WebState, config: dict[str, Any]) -> None:
    try:
        client = GitHubClient(
            token=config["token"],
            min_delay_seconds=config["min_delay_seconds"],
            max_retries=config["max_retries"],
        )
        all_candidates = []
        total_files = 0
        state.log("扫描已开始")

        for query_index, query in enumerate(config["queries"], start=1):
            if state.stop_event.is_set():
                break
            state.log(f"搜索词 {query_index}/{len(config['queries'])}: {query}")
            results = client.search_code(query, pages=config["pages"], per_page=config["per_page"])
            total_files += len(results)
            state.update_metrics(files=total_files, extracted=len(all_candidates))
            state.log(f"返回文件数：{len(results)}")

            for result in results:
                if state.stop_event.is_set():
                    break
                try:
                    text = client.fetch_file_text(result, max_file_bytes=config["max_file_bytes"])
                except GitHubAPIError as exc:
                    state.log(f"跳过文件 {result.repository}/{result.path}：{exc}")
                    continue
                if text is None:
                    continue
                found = extract_candidates(
                    text,
                    source_url=result.html_url,
                    repository=result.repository,
                    path=result.path,
                    include_non_public=config["include_non_public"],
                )
                if found:
                    all_candidates.extend(found)
                    state.update_metrics(files=total_files, extracted=len(all_candidates))
                    state.log(f"{result.repository}/{result.path}: {len(found)}")

        new_count, total_count = append_candidates(
            all_candidates,
            csv_path=state.output_path,
            jsonl_path=state.jsonl_path,
        )
        state.update_metrics(extracted=len(all_candidates), new=new_count, total=total_count)

        if state.stop_event.is_set():
            state.log(f"扫描已停止；新增={new_count} 总数={total_count}")
            state.finish_job("stopped")
        else:
            state.log(f"扫描完成；提取={len(all_candidates)} 新增={new_count} 总数={total_count}")
            state.finish_job("completed")
    except Exception as exc:
        state.log(f"扫描失败：{exc}")
        state.finish_job("failed", error=str(exc))


def run_verify_job(state: WebState, config: dict[str, Any]) -> None:
    try:
        values = load_proxy_values(state.output_path)
        if config["limit"] is not None:
            values = values[: config["limit"]]
        results = []
        state.log(f"验证已开始；数量={len(values)}")

        for index, value in enumerate(values, start=1):
            if state.stop_event.is_set():
                break
            state.log(f"验证 {index}/{len(values)} {value}")
            result = verify_proxy(
                value,
                check_url=config["check_url"],
                timeout_seconds=config["timeout_seconds"],
            )
            results.append(result)
            ok_count = sum(1 for item in results if item.status == "ok")
            state.update_metrics(checked=len(results), ok=ok_count, total=len(values))

        written = write_verification_results(results, state.verified_output_path)
        state.update_metrics(written=written)
        if state.stop_event.is_set():
            state.log(f"验证已停止；写入={written}")
            state.finish_job("stopped")
        else:
            state.log(f"验证完成；写入={written}")
            state.finish_job("completed")
    except Exception as exc:
        state.log(f"验证失败：{exc}")
        state.finish_job("failed", error=str(exc))


def normalize_queries(value: Any) -> list[str]:
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def read_results(path: Path, *, limit: int) -> dict[str, Any]:
    rows = read_csv_rows(path, limit=limit)
    counts: dict[str, int] = {}
    for row in rows["rows"]:
        scheme = row.get("scheme") or "host:port"
        counts[scheme] = counts.get(scheme, 0) + 1
    rows["schemeCounts"] = counts
    return rows


def read_csv_rows(path: Path, *, limit: int) -> dict[str, Any]:
    if not path.exists():
        return {"rows": [], "count": 0, "path": str(path)}

    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    total = len(rows)
    if limit > 0:
        rows = rows[-limit:]
    rows.reverse()
    return {"rows": rows, "count": total, "path": str(path)}


def parse_limit(value: str, *, default: int) -> int:
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(1, min(parsed, 1000))


def iso_local_time() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    raise SystemExit(main())
