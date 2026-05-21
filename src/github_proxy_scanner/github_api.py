from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from .models import SearchResult


class GitHubAPIError(RuntimeError):
    pass


@dataclass
class GitHubClient:
    token: str
    base_url: str = "https://api.github.com"
    timeout_seconds: float = 30.0
    min_delay_seconds: float = 2.0
    max_retries: int = 3
    max_retry_sleep_seconds: float = 120.0
    user_agent: str = "github-proxy-scanner/0.1"

    def __post_init__(self) -> None:
        self._last_request_at = 0.0

    def search_code(
        self,
        query: str,
        *,
        pages: int,
        per_page: int,
    ) -> list[SearchResult]:
        results: list[SearchResult] = []
        for page in range(1, pages + 1):
            payload = self.request_json(
                "/search/code",
                params={
                    "q": query,
                    "page": str(page),
                    "per_page": str(per_page),
                },
            )
            for item in payload.get("items", []):
                repository = item.get("repository") or {}
                results.append(
                    SearchResult(
                        repository=repository.get("full_name", ""),
                        path=item.get("path", ""),
                        html_url=item.get("html_url", ""),
                        api_url=item.get("url", ""),
                    )
                )
        return results

    def fetch_file_text(self, result: SearchResult, *, max_file_bytes: int) -> Optional[str]:
        payload = self.request_json(result.api_url)

        if payload.get("type") != "file":
            return None

        size = payload.get("size")
        if isinstance(size, int) and size > max_file_bytes:
            return None

        content = payload.get("content")
        encoding = payload.get("encoding")
        if not content or encoding != "base64":
            return None

        try:
            raw = base64.b64decode(content, validate=False)
        except ValueError as exc:
            raise GitHubAPIError(f"Could not decode {result.html_url}: {exc}") from exc

        if len(raw) > max_file_bytes:
            return None

        return raw.decode("utf-8", errors="replace")

    def request_json(self, path_or_url: str, params: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
        body = self._request_bytes(path_or_url, params=params)
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise GitHubAPIError(f"GitHub returned non-JSON response for {path_or_url}") from exc

    def _request_bytes(self, path_or_url: str, params: Optional[Mapping[str, str]] = None) -> bytes:
        url = self._build_url(path_or_url, params)
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": self.user_agent,
            "X-GitHub-Api-Version": "2022-11-28",
        }

        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    return response.read()
            except ValueError as exc:
                raise GitHubAPIError(f"Invalid GitHub API URL: {url}") from exc
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                if exc.code in {403, 429} and attempt < self.max_retries:
                    delay = self._retry_delay(exc.headers, attempt)
                    if delay <= self.max_retry_sleep_seconds:
                        time.sleep(delay)
                        continue
                raise GitHubAPIError(self._format_http_error(exc.code, body, exc.headers)) from exc
            except urllib.error.URLError as exc:
                if attempt < self.max_retries:
                    time.sleep(min(2**attempt, 30))
                    continue
                raise GitHubAPIError(f"Network error calling GitHub: {exc}") from exc

        raise GitHubAPIError("Request failed after retries")

    def _build_url(self, path_or_url: str, params: Optional[Mapping[str, str]]) -> str:
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            url = path_or_url
        else:
            url = f"{self.base_url.rstrip('/')}/{path_or_url.lstrip('/')}"

        if not params:
            return self._sanitize_url(url)

        separator = "&" if "?" in url else "?"
        return self._sanitize_url(f"{url}{separator}{urllib.parse.urlencode(params)}")

    def _sanitize_url(self, url: str) -> str:
        parts = urllib.parse.urlsplit(url)
        path = urllib.parse.quote(parts.path, safe="/%:@")
        query = urllib.parse.quote(parts.query, safe="=&%:+,/?@")
        fragment = urllib.parse.quote(parts.fragment, safe="=&%:+,/?@")
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, fragment))

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_delay_seconds:
            time.sleep(self.min_delay_seconds - elapsed)
        self._last_request_at = time.monotonic()

    def _retry_delay(self, headers: Mapping[str, str], attempt: int) -> float:
        retry_after = headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass

        remaining = headers.get("X-RateLimit-Remaining")
        reset_at = headers.get("X-RateLimit-Reset")
        if remaining == "0" and reset_at:
            try:
                return max(0.0, float(reset_at) - time.time() + 2)
            except ValueError:
                pass

        return min(10 * (2**attempt), self.max_retry_sleep_seconds)

    def _format_http_error(self, status_code: int, body: str, headers: Mapping[str, str]) -> str:
        message = body.strip()
        try:
            payload = json.loads(body)
            message = payload.get("message", message)
        except json.JSONDecodeError:
            pass

        reset_at = headers.get("X-RateLimit-Reset")
        if reset_at:
            try:
                reset_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(reset_at)))
                return f"GitHub API error {status_code}: {message}. Rate limit reset: {reset_text}"
            except ValueError:
                pass
        return f"GitHub API error {status_code}: {message}"
