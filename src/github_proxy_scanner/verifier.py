from __future__ import annotations

import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .models import VerificationResult


def verify_proxy(value: str, *, check_url: str, timeout_seconds: float) -> VerificationResult:
    parsed = urlparse(value if "://" in value else f"http://{value}")
    scheme = parsed.scheme.lower()

    if scheme not in {"http", "https"}:
        return VerificationResult(
            value=value,
            status="skipped",
            http_status=None,
            elapsed_ms=None,
            error=f"Built-in verifier does not support {scheme}",
        )

    proxy_url = value if "://" in value else f"http://{value}"
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    )
    request = urllib.request.Request(
        check_url,
        headers={"User-Agent": "github-proxy-scanner/0.1"},
    )

    started = time.monotonic()
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            response.read(256)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            status = "ok" if 200 <= response.status < 400 else "bad"
            return VerificationResult(
                value=value,
                status=status,
                http_status=response.status,
                elapsed_ms=elapsed_ms,
                error="",
            )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return VerificationResult(
            value=value,
            status="bad",
            http_status=None,
            elapsed_ms=elapsed_ms,
            error=str(exc),
        )
