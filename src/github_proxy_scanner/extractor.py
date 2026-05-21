from __future__ import annotations

import ipaddress
import re
from typing import Iterable, Set, Tuple

from .models import ProxyCandidate

SCHEME_RE = r"https?|socks4|socks5"
IPV4_RE = (
    r"(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
)
LABEL_RE = r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)"
DOMAIN_RE = rf"(?:{LABEL_RE}\.)+[A-Za-z]{{2,63}}"
HOST_RE = rf"(?:{IPV4_RE}|{DOMAIN_RE})"

PROXY_PATTERN = re.compile(
    rf"(?<![\w@:/.-])(?:(?P<scheme>{SCHEME_RE})://)?(?P<host>{HOST_RE}):(?P<port>\d{{2,5}})(?![\w@.-])",
    re.IGNORECASE,
)


def is_public_host(host: str) -> bool:
    normalized = host.strip().lower()
    if normalized == "localhost" or normalized.endswith(".local"):
        return False

    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return True

    return address.is_global


def normalize_candidate(scheme: str | None, host: str, port: int) -> str:
    normalized_host = host.lower()
    if scheme:
        return f"{scheme.lower()}://{normalized_host}:{port}"
    return f"{normalized_host}:{port}"


def extract_candidates(
    text: str,
    *,
    source_url: str,
    repository: str,
    path: str,
    include_non_public: bool = False,
) -> list[ProxyCandidate]:
    candidates: list[ProxyCandidate] = []
    seen: Set[Tuple[str, int]] = set()

    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in PROXY_PATTERN.finditer(line):
            scheme = match.group("scheme")
            host = match.group("host")
            raw_port = match.group("port")

            try:
                port = int(raw_port)
            except ValueError:
                continue

            if port < 1 or port > 65535:
                continue

            if not include_non_public and not is_public_host(host):
                continue

            value = normalize_candidate(scheme, host, port)
            key = (value, line_number)
            if key in seen:
                continue
            seen.add(key)

            candidates.append(
                ProxyCandidate(
                    value=value,
                    host=host.lower(),
                    port=port,
                    scheme=scheme.lower() if scheme else None,
                    source_url=source_url,
                    repository=repository,
                    path=path,
                    line=line_number,
                )
            )

    return candidates


def extract_values(text: str, include_non_public: bool = False) -> Iterable[str]:
    for candidate in extract_candidates(
        text,
        source_url="local",
        repository="local",
        path="local",
        include_non_public=include_non_public,
    ):
        yield candidate.value
