"""First-party domain seeding and allow-list helpers."""

from __future__ import annotations

from urllib.parse import urlparse

from schema import EXTRA_SEED_DOMAINS, VENDOR_DOC_HOSTS


def registrable_domain(host: str) -> str:
    """Best-effort registrable domain (no public-suffix list dependency)."""
    host = host.lower().strip().lstrip(".")
    if not host:
        return ""
    parts = host.split(".")
    if len(parts) >= 2:
        # keep last two labels; good enough for com/io/dev/ai
        return ".".join(parts[-2:])
    return host


def host_of(url: str | None) -> str:
    if not url:
        return ""
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def seed_first_party_domains(app: dict) -> list[str]:
    """
    Seed from hint_url registrable domain + EXTRA_SEED_DOMAINS.
    Gemini may only ADD to this list, never replace.
    """
    seeds: list[str] = []
    hint_url = app.get("hint_url")
    h = host_of(hint_url)
    if h:
        seeds.append(h)
        rd = registrable_domain(h)
        if rd and rd not in seeds:
            seeds.append(rd)

    for d in EXTRA_SEED_DOMAINS.get(app.get("app_name", ""), ()):
        if d not in seeds:
            seeds.append(d)

    # de-dupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for d in seeds:
        d = d.lower()
        if d and d not in seen:
            seen.add(d)
            out.append(d)
    return out


def merge_discovered_domains(seeded: list[str], discovered: list[str]) -> list[str]:
    """
    Gemini may only ADD clearly vendor-controlled hosts.
    Never drop seeded entries.
    """
    allowed_additions: list[str] = []
    for raw in discovered or []:
        d = (raw or "").lower().strip()
        if not d:
            continue
        if _is_allowed_addition(d, seeded):
            allowed_additions.append(d)

    seen = set(seeded)
    out = list(seeded)
    for d in allowed_additions:
        host = d
        # store hostname-like forms
        if host not in seen:
            seen.add(host)
            out.append(host)
        rd = registrable_domain(host)
        if rd and rd not in seen:
            seen.add(rd)
            out.append(rd)
    return out


def _is_allowed_addition(domain: str, seeded: list[str]) -> bool:
    d = domain.lower()
    # already covered
    for s in seeded:
        if d == s or d.endswith("." + s) or s.endswith("." + d):
            return True
    # vendor doc hosts
    for vh in VENDOR_DOC_HOSTS:
        if d == vh or d.endswith("." + vh):
            return True
    # GitHub org / pages
    if d == "github.com" or d.endswith(".github.io") or d.endswith(".githubusercontent.com"):
        return True
    # LinkedIn docs on Microsoft Learn
    if d == "learn.microsoft.com" or d.endswith(".learn.microsoft.com"):
        return True
    # subdomain of a seeded registrable domain
    for s in seeded:
        rd = registrable_domain(s)
        if rd and (d == rd or d.endswith("." + rd)):
            return True
    return False


def domain_in_first_party(url: str, first_party_domains: list[str]) -> bool:
    h = host_of(url)
    if not h:
        return False
    for d in first_party_domains:
        d = d.lower()
        if h == d or h.endswith("." + d):
            return True
        if registrable_domain(h) == registrable_domain(d):
            return True
    # LinkedIn special case
    if "linkedin" in " ".join(first_party_domains) or any(
        "linkedin" in x for x in first_party_domains
    ):
        if h == "learn.microsoft.com" or h.endswith(".learn.microsoft.com"):
            return True
    if any(x.endswith("linkedin.com") or "linkedin" in x for x in first_party_domains):
        if "learn.microsoft.com" in h:
            return True
    # Also allow learn.microsoft.com if path context was LinkedIn — domain list may include it
    for d in first_party_domains:
        if "learn.microsoft.com" in d and h.endswith("learn.microsoft.com"):
            return True
    return False
