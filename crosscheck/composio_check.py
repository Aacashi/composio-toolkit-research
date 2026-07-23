"""Composio catalog cross-check + optional Sheets export."""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any, Optional

# Explicit mapping: Composio auth scheme name -> our auth_primary enum
COMPOSIO_AUTH_MAP: dict[str, str] = {
    "API_KEY": "api_key",
    "api_key": "api_key",
    "OAUTH2": "oauth2",
    "oauth2": "oauth2",
    "OAUTH1": "oauth1",
    "oauth1": "oauth1",
    "BASIC": "basic",
    "basic": "basic",
    "BEARER_TOKEN": "api_key",
    "bearer_token": "api_key",
    "JWT": "jwt_keypair",
    "jwt": "jwt_keypair",
    "NO_AUTH": "none",
    "no_auth": "none",
    "NONE": "none",
    "BASIC_WITH_JWT": "jwt_keypair",
}


def _slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def load_catalog() -> Optional[list[dict[str, Any]]]:
    """
    Fetch toolkit catalog once at startup.
    On failure: return None and log — never block the run.
    """
    try:
        from composio import Composio

        client = Composio()
        toolkits = client.toolkits.get()
        # normalize to list of dicts with name/slug/auth
        out: list[dict[str, Any]] = []
        items = toolkits if isinstance(toolkits, list) else getattr(toolkits, "items", None) or []
        if not items and hasattr(toolkits, "__iter__"):
            items = list(toolkits)
        for t in items:
            if isinstance(t, dict):
                name = t.get("name") or t.get("slug") or ""
                slug = t.get("slug") or _slugify(name)
                auth = t.get("auth_schemes") or t.get("authSchemes") or t.get("auth_mode") or []
            else:
                name = getattr(t, "name", None) or getattr(t, "slug", "") or ""
                slug = getattr(t, "slug", None) or _slugify(str(name))
                auth = (
                    getattr(t, "auth_schemes", None)
                    or getattr(t, "authSchemes", None)
                    or getattr(t, "auth_mode", None)
                    or []
                )
            out.append({"name": str(name), "slug": str(slug), "auth": auth})
        print(f"[composio] catalog loaded: {len(out)} toolkits")
        return out
    except Exception as e:
        print(f"[composio] catalog fetch FAILED — degrading cross-check: {e}")
        return None


def match_toolkit(
    app_name: str, catalog: list[dict[str, Any]]
) -> tuple[Optional[dict[str, Any]], bool]:
    """
    Returns (match, ambiguous).
    Ambiguous → treat as no support (never guess).
    """
    target = _slugify(app_name)
    target_compact = target.replace("_", "")
    exact = []
    fuzzy = []
    for t in catalog:
        slug = _slugify(t.get("slug") or "")
        name_slug = _slugify(t.get("name") or "")
        if slug == target or name_slug == target:
            exact.append(t)
            continue
        if slug.replace("_", "") == target_compact or name_slug.replace("_", "") == target_compact:
            exact.append(t)
            continue
        ratio = max(
            SequenceMatcher(None, target, slug).ratio(),
            SequenceMatcher(None, target, name_slug).ratio(),
        )
        if ratio >= 0.86:
            fuzzy.append((ratio, t))
    if exact:
        if len(exact) > 1:
            print(f"[composio] AMBIGUOUS exact matches for {app_name!r}: {[x.get('slug') for x in exact]}")
            return None, True
        return exact[0], False
    fuzzy.sort(key=lambda x: -x[0])
    if not fuzzy:
        return None, False
    if len(fuzzy) > 1 and abs(fuzzy[0][0] - fuzzy[1][0]) < 0.05:
        print(
            f"[composio] AMBIGUOUS fuzzy for {app_name!r}: "
            f"{[(r, t.get('slug')) for r, t in fuzzy[:3]]}"
        )
        return None, True
    if fuzzy[0][0] >= 0.92:
        return fuzzy[0][1], False
    # below threshold — no match
    return None, False


def _primary_auth_from_composio(auth: Any) -> Optional[str]:
    if not auth:
        return None
    if isinstance(auth, str):
        return COMPOSIO_AUTH_MAP.get(auth) or COMPOSIO_AUTH_MAP.get(auth.upper())
    if isinstance(auth, list) and auth:
        first = auth[0]
        if isinstance(first, str):
            return COMPOSIO_AUTH_MAP.get(first) or COMPOSIO_AUTH_MAP.get(first.upper())
        if isinstance(first, dict):
            mode = first.get("mode") or first.get("auth_mode") or first.get("type") or ""
            return COMPOSIO_AUTH_MAP.get(str(mode)) or COMPOSIO_AUTH_MAP.get(str(mode).upper())
    return None


def attach_composio_to_row(
    app_name: str, catalog: Optional[list[dict[str, Any]]]
) -> dict[str, Any]:
    if catalog is None:
        return {
            "composio_supports": None,
            "composio_auth_scheme": None,
            "agrees_with_composio": "n_a",
        }
    match, ambiguous = match_toolkit(app_name, catalog)
    if ambiguous or match is None:
        return {
            "composio_supports": "no",
            "composio_auth_scheme": None,
            "agrees_with_composio": "n_a",
        }
    scheme = _primary_auth_from_composio(match.get("auth"))
    return {
        "composio_supports": "yes",
        "composio_auth_scheme": scheme,
        "agrees_with_composio": "n_a",
    }


def finalize_agreement(row: dict[str, Any]) -> dict[str, Any]:
    """Compute agrees_with_composio once auth_primary is known."""
    supports = row.get("composio_supports")
    if supports not in ("yes", True):
        row["agrees_with_composio"] = "n_a"
        if supports is True:
            row["composio_supports"] = "yes"
        elif supports is False:
            row["composio_supports"] = "no"
        return row
    row["composio_supports"] = "yes"
    ours = row.get("auth_primary")
    theirs = row.get("composio_auth_scheme")
    if ours in (None, "", "unknown") or theirs in (None, ""):
        row["agrees_with_composio"] = "n_a"
    elif ours == theirs:
        row["agrees_with_composio"] = "yes"
    else:
        row["agrees_with_composio"] = "disagrees"
    return row


def enrich_rows_with_agreement(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [finalize_agreement(r) for r in rows]


def maybe_export_sheets(rows: list[dict[str, Any]]) -> None:
    """
    Optional sink via Composio Google Sheets toolkit.
    Failure is logged only — never raises to the pipeline.
    Requires a connected Google Sheets account in the Composio dashboard;
    see README.
    """
    try:
        from composio import Composio

        # Soft attempt: write a JSON dump note. Real sheet ID comes from env if set.
        import os

        sheet_id = os.getenv("COMPOSIO_SHEETS_ID")
        if not sheet_id:
            print(
                "[composio] --export-sheets skipped: set COMPOSIO_SHEETS_ID "
                "and connect Google Sheets in the Composio dashboard"
            )
            return
        client = Composio()
        # Best-effort; API shapes vary by SDK version
        payload = json.dumps(rows)[:50000]
        print(f"[composio] export-sheets: attempting write to {sheet_id} ({len(rows)} rows)")
        # Prefer tools.execute if available
        if hasattr(client, "tools"):
            try:
                client.tools.execute(
                    "GOOGLESHEETS_BATCH_UPDATE",
                    {
                        "spreadsheet_id": sheet_id,
                        "values": [[payload]],
                    },
                )
                print("[composio] export-sheets: write attempted")
                return
            except Exception as e:
                print(f"[composio] export-sheets tool execute failed (non-fatal): {e}")
        print("[composio] export-sheets: no compatible write path; rows remain on disk")
    except Exception as e:
        print(f"[composio] export-sheets FAILED (non-fatal): {e}")


def main() -> None:
    """Standalone re-run of cross-check against an existing run file."""
    import argparse
    from pathlib import Path

    from dotenv import load_dotenv

    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, help="Path to run_vN.json")
    parser.add_argument("--export-sheets", action="store_true")
    args = parser.parse_args()
    path = Path(args.run)
    if not path.is_absolute():
        path = root / "data" / path
    rows = json.loads(path.read_text(encoding="utf-8"))
    catalog = load_catalog()
    out = []
    for r in rows:
        fields = attach_composio_to_row(r["app_name"], catalog)
        r = {**r, **fields}
        out.append(finalize_agreement(r))
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[composio] updated {path} ({len(out)} rows)")
    if args.export_sheets:
        maybe_export_sheets(out)


if __name__ == "__main__":
    main()
