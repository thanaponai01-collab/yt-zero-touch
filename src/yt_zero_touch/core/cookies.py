"""
Cookie Utilities — Inspection, Validation, and Netscape Serialization.
======================================================================
Provides inspection for Netscape cookie files (detecting expired tokens,
domains, and lifespan) and serializes Playwright browser cookies into
standard Netscape format compatible with yt-dlp, gallery-dl, and curl.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path


_CRITICAL_COOKIE_NAMES = {
    # YouTube / Google
    "__Secure-3PSID",
    "__Secure-1PSIDTS",
    "__Secure-3PSIDTS",
    "SID",
    "LOGIN_INFO",
    # Instagram
    "sessionid",
    "ds_user_id",
    # Twitter / X
    "auth_token",
    "ct0",
    # Facebook
    "c_user",
    "xs",
}

_KNOWN_DOMAINS = {
    "youtube.com": "YouTube",
    "google.com": "Google",
    "instagram.com": "Instagram",
    "twitter.com": "Twitter/X",
    "x.com": "Twitter/X",
    "facebook.com": "Facebook",
    "reddit.com": "Reddit",
}


@dataclass(frozen=True)
class CookieRecord:
    domain: str
    include_subdomains: bool
    path: str
    secure: bool
    expires: int
    name: str
    value: str
    http_only: bool = False

    @property
    def is_session(self) -> bool:
        return self.expires <= 0

    def is_expired(self, now: float | None = None) -> bool:
        if self.is_session:
            return False
        current = time.time() if now is None else now
        return self.expires < current


@dataclass(frozen=True)
class CookieStatus:
    path: Path | None
    valid: bool
    status: str  # "active", "expired", "expiring_soon", "empty", "missing", "none"
    domains: list[str] = field(default_factory=list)
    days_left: float | None = None
    summary: str = ""
    details: list[str] = field(default_factory=list)


def parse_netscape_lines(lines: list[str]) -> list[CookieRecord]:
    """Parse Netscape cookie file lines into CookieRecord instances."""
    records: list[CookieRecord] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue

        http_only = False
        if line.startswith("#HttpOnly_"):
            http_only = True
            line = line[len("#HttpOnly_"):]
        elif line.startswith("#"):
            continue

        parts = line.split("\t")
        if len(parts) < 7:
            # Try splitting by whitespace if tabs are lost
            parts = line.split()
            if len(parts) < 7:
                continue

        domain = parts[0]
        include_sub = parts[1].strip().upper() == "TRUE"
        path = parts[2]
        secure = parts[3].strip().upper() == "TRUE"
        try:
            expires = int(parts[4])
        except (ValueError, TypeError):
            expires = 0
        name = parts[5]
        value = parts[6] if len(parts) > 6 else ""

        records.append(
            CookieRecord(
                domain=domain,
                include_subdomains=include_sub,
                path=path,
                secure=secure,
                expires=expires,
                name=name,
                value=value,
                http_only=http_only,
            )
        )
    return records


def inspect_cookie_file(
    path: Path | str | None,
    now: float | None = None,
) -> CookieStatus:
    """Analyze a cookie file for expiration, domains, and health."""
    if not path:
        return CookieStatus(
            path=None,
            valid=False,
            status="none",
            domains=[],
            days_left=None,
            summary="No cookies loaded",
            details=["No cookie file configured."],
        )

    file_path = Path(path)
    if not file_path.exists():
        return CookieStatus(
            path=file_path,
            valid=False,
            status="missing",
            domains=[],
            days_left=None,
            summary=f"Missing: {file_path.name}",
            details=[f"Cookie file not found at {file_path}"],
        )

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return CookieStatus(
            path=file_path,
            valid=False,
            status="error",
            domains=[],
            days_left=None,
            summary="Cannot read file",
            details=[f"Error reading {file_path.name}: {exc}"],
        )

    records = parse_netscape_lines(content.splitlines())
    if not records:
        return CookieStatus(
            path=file_path,
            valid=False,
            status="empty",
            domains=[],
            days_left=None,
            summary=f"Empty ({file_path.name})",
            details=["File contains no valid Netscape cookie entries."],
        )

    current_time = time.time() if now is None else now

    # Map recognizable domains
    detected_domains: set[str] = set()
    for r in records:
        dom = r.domain.lstrip(".").lower()
        for k_dom, label in _KNOWN_DOMAINS.items():
            if k_dom in dom:
                detected_domains.add(label)
                break
        else:
            if dom:
                detected_domains.add(dom)

    domain_list = sorted(detected_domains)
    dom_summary = ", ".join(domain_list[:2]) if domain_list else "Unknown"
    if len(domain_list) > 2:
        dom_summary += f" +{len(domain_list) - 2}"

    # Evaluate expiration
    critical_records = [r for r in records if r.name in _CRITICAL_COOKIE_NAMES]
    target_records = critical_records if critical_records else records

    # Check for expired cookies among target records
    expired_critical = [r for r in target_records if not r.is_session and r.expires < current_time]
    active_timed = [r for r in records if not r.is_session and r.expires >= current_time]

    if expired_critical and len(expired_critical) == len(target_records):
        return CookieStatus(
            path=file_path,
            valid=False,
            status="expired",
            domains=domain_list,
            days_left=0.0,
            summary=f"Expired ({dom_summary})",
            details=[
                f"Critical auth cookies in {file_path.name} have expired.",
                f"Expired tokens: {', '.join(sorted({r.name for r in expired_critical}))}",
            ],
        )

    if active_timed:
        min_expiry = min(r.expires for r in active_timed)
        days_left = max(0.0, (min_expiry - current_time) / 86400.0)
    else:
        # All session cookies
        days_left = None

    if days_left is not None and days_left < 1.0:
        hours = int(days_left * 24)
        summary = f"Expiring soon ({dom_summary} • {hours}h left)"
        status = "expiring_soon"
    elif days_left is not None:
        summary = f"Active ({dom_summary} • {int(days_left)}d left)"
        status = "active"
    else:
        summary = f"Active ({dom_summary} • Session)"
        status = "active"

    details = [
        f"File: {file_path.name} ({len(records)} cookies)",
        f"Detected platforms: {', '.join(domain_list) if domain_list else 'None'}",
    ]
    if days_left is not None:
        details.append(f"Earliest expiration in {days_left:.1f} days.")
    else:
        details.append("Session cookies only (valid until browser close).")

    return CookieStatus(
        path=file_path,
        valid=True,
        status=status,
        domains=domain_list,
        days_left=days_left,
        summary=summary,
        details=details,
    )


def export_playwright_cookies(cookies: list[dict], dest_path: Path | str) -> int:
    """Format and save a list of Playwright cookies to a Netscape cookie file.

    Returns the number of cookies saved.
    """
    out_file = Path(dest_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Netscape HTTP Cookie File",
        "# http://curl.haxx.se/rfc/cookie_spec.html",
        "# Exported by YT-DLP Zero-Touch Login Vault. Do not edit directly.",
        "",
    ]

    count = 0
    for c in cookies:
        name = c.get("name", "")
        value = c.get("value", "")
        domain = c.get("domain", "")
        path = c.get("path", "/")
        secure = "TRUE" if c.get("secure", False) else "FALSE"
        http_only = c.get("httpOnly", False)
        raw_expires = c.get("expires", -1)

        try:
            expires = int(raw_expires) if raw_expires > 0 else 0
        except (ValueError, TypeError):
            expires = 0

        # Subdomains flag: true if domain starts with a dot or has internal dots
        include_sub = "TRUE" if domain.startswith(".") or domain.count(".") >= 2 else "FALSE"

        prefix = "#HttpOnly_" if http_only else ""
        line = f"{prefix}{domain}\t{include_sub}\t{path}\t{secure}\t{expires}\t{name}\t{value}"
        lines.append(line)
        count += 1

    out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return count
