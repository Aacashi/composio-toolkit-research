"""Schema enums, models, and constants — AMENDMENT_3."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

# Bump whenever prompts/ or this schema's Gemini surface changes.
PROMPTS_VERSION = "v3"


class BusinessType(str, Enum):
    infra_usage_based = "infra_usage_based"
    saas_seat_based = "saas_seat_based"
    ad_platform = "ad_platform"
    data_vendor = "data_vendor"
    commerce_platform = "commerce_platform"
    enterprise_sales = "enterprise_sales"
    ai_native = "ai_native"


class DocsAccess(str, Enum):
    public = "public"
    login_required = "login_required"
    on_request = "on_request"
    none_found = "none_found"


class AuthScheme(str, Enum):
    api_key = "api_key"
    pat = "pat"
    oauth2 = "oauth2"
    oauth1 = "oauth1"
    basic = "basic"
    jwt_keypair = "jwt_keypair"
    hmac_signed = "hmac_signed"
    aws_sigv4 = "aws_sigv4"
    session_only = "session_only"
    none = "none"
    unknown = "unknown"


class AccessTier(str, Enum):
    open = "open"
    self_serve_free = "self_serve_free"
    self_serve_trial = "self_serve_trial"
    card_required = "card_required"
    plan_gated = "plan_gated"
    approval_gated = "approval_gated"
    partner_gated = "partner_gated"
    no_public_access = "no_public_access"


class AccessTierRollup(str, Enum):
    open = "open"
    paid = "paid"
    gated = "gated"


class ApiType(str, Enum):
    rest = "rest"
    graphql = "graphql"
    both = "both"
    cli_only = "cli_only"
    none = "none"
    unknown = "unknown"


class YesNoUnknown(str, Enum):
    yes = "yes"
    no = "no"
    unknown = "unknown"


class McpExists(str, Enum):
    official_open = "official_open"
    official_gated = "official_gated"
    community = "community"
    none = "none"
    unknown = "unknown"


class Buildability(str, Enum):
    easy_win = "easy_win"
    easy_but_paid = "easy_but_paid"
    needs_review = "needs_review"
    needs_outreach = "needs_outreach"
    blocked = "blocked"
    unknown = "unknown"


class BlockerType(str, Enum):
    none = "none"
    payment = "payment"
    vendor_review = "vendor_review"
    partnership = "partnership"
    no_api = "no_api"
    no_docs = "no_docs"
    unknown = "unknown"


class Unblocker(str, Enum):
    nobody = "nobody"
    composio_finance = "composio_finance"
    vendor_human = "vendor_human"
    composio_bd = "composio_bd"
    n_a = "n_a"


class Confidence(str, Enum):
    high = "high"
    med = "med"
    low = "low"


class Flag(str, Enum):
    unsourced = "unsourced"
    thin_content = "thin_content"
    no_docs_found = "no_docs_found"
    schema_fail = "schema_fail"
    chunked = "chunked"
    retry_used = "retry_used"
    hint_unconfirmed = "hint_unconfirmed"
    second_round_used = "second_round_used"
    business_type_unconfirmed = "business_type_unconfirmed"


GEMINI_FACT_FIELDS = (
    "docs_access",
    "access_tier",
    "auth_primary",
    "api_type",
    "mcp_exists",
    "has_openapi_spec",
    "needs_instance_url",
    "has_webhooks",
    "is_open_source",
)

ATOMIC_ENUM_FIELDS = GEMINI_FACT_FIELDS

DERIVED_FIELDS = (
    "access_tier_rollup",
    "buildability",
    "unblocker",
    "blocker_type",
    "blocker",
)

PRIMARY_SCORED = ("access_tier", "auth_primary")
SECONDARY_SCORED = (
    "business_type",
    "docs_access",
    "api_type",
    "has_openapi_spec",
    "needs_instance_url",
    "has_webhooks",
    "mcp_exists",
    "is_open_source",
)
DERIVED_SCORED = ("access_tier_rollup", "buildability", "blocker_type", "unblocker")

HINT_FIELD_MAP: dict[str, tuple[str, ...]] = {
    "Otter AI": ("mcp_exists",),
    "Devin": ("mcp_exists",),
    "Consensus": ("auth_primary",),
    "NotebookLM": ("access_tier", "api_type"),
    "PitchBook": ("api_type", "access_tier"),
    "Twenty": ("is_open_source",),
}

EXTRA_SEED_DOMAINS: dict[str, tuple[str, ...]] = {
    "Harvest": ("harvestapp.com", "getharvest.com"),
}

VENDOR_DOC_HOSTS = (
    "stoplight.io",
    "readme.io",
    "mintlify.com",
    "gitbook.io",
    "postman.co",
    "postman.com",
    "apiary.io",
    "swagger.io",
    "swaggerhub.com",
)


class BackupLink(BaseModel):
    url: str
    why: str


class DiscoverResult(BaseModel):
    one_liner: str = ""
    business_type: str
    business_type_reason: str = ""
    first_party_domains: list[str] = Field(default_factory=list)
    auth_url: Optional[str] = None
    pricing_url: Optional[str] = None
    api_index_url: Optional[str] = None
    openapi_url: Optional[str] = None
    webhooks_url: Optional[str] = None
    mcp_url: Optional[str] = None
    backup_links: list[BackupLink] = Field(default_factory=list)


class ExtractResult(BaseModel):
    """Atomic facts only. No verdict fields. No business_type overwrite."""

    one_liner: str = ""
    business_type_supported: str = "yes"  # transient; becomes flag if no
    docs_access: str = "unknown"
    auth_primary: str = "unknown"
    auth_detail: str = ""
    access_tier: str = "unknown"
    access_cost_note: str = ""
    api_type: str = "unknown"
    has_openapi_spec: str = "unknown"
    needs_instance_url: str = "unknown"
    has_webhooks: str = "unknown"
    mcp_exists: str = "unknown"
    is_open_source: str = "unknown"
    evidence: dict[str, str] = Field(default_factory=dict)
    confidence: dict[str, str] = Field(default_factory=dict)
    notes: str = ""


def empty_unknown_row(
    app: dict[str, Any],
    *,
    flags: list[str] | None = None,
    docs_access: str = "unknown",
) -> dict[str, Any]:
    confidence = {f: "low" for f in GEMINI_FACT_FIELDS}
    return {
        "app_name": app["app_name"],
        "category": app.get("category", ""),
        "one_liner": "",
        "business_type": "ai_native",
        "docs_access": docs_access,
        "auth_primary": "unknown",
        "auth_detail": "",
        "access_tier": "unknown",
        "access_cost_note": "",
        "api_type": "unknown",
        "has_openapi_spec": "unknown",
        "needs_instance_url": "unknown",
        "has_webhooks": "unknown",
        "mcp_exists": "unknown",
        "is_open_source": "unknown",
        "evidence": {},
        "confidence": confidence,
        "flags": list(flags or []),
        "sources_fetched": [],
        "first_party_domains": [],
        "backup_links": [],
        "notes": "",
        "run_id": "",
    }


ALLOWED_VALUES: dict[str, tuple[str, ...]] = {
    "business_type": tuple(e.value for e in BusinessType),
    "docs_access": tuple(e.value for e in DocsAccess),
    "auth_primary": tuple(e.value for e in AuthScheme),
    "access_tier": tuple(e.value for e in AccessTier),
    "access_tier_rollup": tuple(e.value for e in AccessTierRollup),
    "api_type": tuple(e.value for e in ApiType),
    "has_openapi_spec": tuple(e.value for e in YesNoUnknown),
    "needs_instance_url": tuple(e.value for e in YesNoUnknown),
    "has_webhooks": tuple(e.value for e in YesNoUnknown),
    "mcp_exists": tuple(e.value for e in McpExists),
    "is_open_source": tuple(e.value for e in YesNoUnknown),
    "buildability": tuple(e.value for e in Buildability),
    "blocker_type": tuple(e.value for e in BlockerType),
    "unblocker": tuple(e.value for e in Unblocker),
    "business_type_supported": ("yes", "no"),
}
