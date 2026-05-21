from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class SearchResult:
    repository: str
    path: str
    html_url: str
    api_url: str


@dataclass(frozen=True)
class ProxyCandidate:
    value: str
    host: str
    port: int
    scheme: Optional[str]
    source_url: str
    repository: str
    path: str
    line: int
    discovered_at: str = field(default_factory=utc_now_iso)

    def to_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class VerificationResult:
    value: str
    status: str
    http_status: Optional[int]
    elapsed_ms: Optional[int]
    error: str
    checked_at: str = field(default_factory=utc_now_iso)

    def to_record(self) -> dict:
        return asdict(self)
