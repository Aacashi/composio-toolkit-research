"""Schema enums, models, and constants for the research pipeline."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# Bump whenever any prompt file under prompts/ changes.
PROMPTS_VERSION = "v1"


class BusinessType(str, Enum):
    infra_usage_based = "infra_usage_based"
    saas_seat_based = "saas_seat_based"
    ad_platform = "ad_platform"
    data_vendor = "data_vendor"
    commerce_platform = "commerce_platform"
    enterprise_sales = "enterprise_sales"
    open_source = "open_source"
    ai_native = "ai_native"


class DocsAccess(str, Enum):
    public = "public"
    login_required = "login_required"
    on_request = "on_request"
    none_found = "none_found"


class DocsLocation(str, Enum):
    own_domain = "own_domain"
    docs_subdomain = "docs_subdomain"
    third_party_host = "third_party_host"
    none = "none"


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
    # self_hosted retired (LOGIC_FREEZE §4)


class ApiType(str, Enum):
    rest = "rest"
    graphql = "graphql"
    both = "both"
    soap = "soap"
    sdk_only = "sdk_only"
    cli_tool = "cli_tool"
    none = "none"
    unknown = "unknown"


class ApiBreadth(str, Enum):
    narrow = "narrow"
    medium = "medium"
    broad = "broad"
    unknown = "unknown"


class YesNoUnknown(str, Enum):
    yes = "yes"
    no = "no"
    unknown = "unknown"


class McpExists(str, Enum):
    official = "official"
    community = "community"
    none = "none"
    unknown = "unknown"


class McpAccess(str, Enum):
    same_as_api = "same_as_api"
    paid_only = "paid_only"
    waitlist = "waitlist"
    n_a = "n_a"


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


class WaitClass(str, Enum):
    none = "none"
    hours = "hours"
    days = "days"
    weeks = "weeks"
    months = "months"
    n_a = "n_a"
    unknown = "unknown"


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


# Atomic fields Gemini may emit (extract). Verdict fields are code-derived.
ATOMIC_ENUM_FIELDS = (
    "docs_access",
    "docs_location",
    "auth_primary",
    "access_tier",
    "api_type",
    "api_breadth",
    "has_openapi_spec",
    "needs_instance_url",
    "has_webhooks",
    "mcp_exists",
    "mcp_access",
)

DERIVED_FIELDS = (
    "buildability",
    "unblocker",
    "wait_class",
    "blocker_type",
    "blocker",
)

# Scored against ground truth (atoms). Derived reported separately.
PRIMARY_SCORED = ("access_tier", "auth_primary")
SECONDARY_SCORED = (
    "business_type",
    "docs_access",
    "docs_location",
    "api_type",
    "api_breadth",
    "has_openapi_spec",
    "needs_instance_url",
    "has_webhooks",
    "mcp_exists",
    "mcp_access",
)
DERIVED_SCORED = ("buildability", "blocker_type", "unblocker", "wait_class")

# Hint note -> fields that need first-party evidence (LOGIC_FREEZE §10)
HINT_FIELD_MAP: dict[str, tuple[str, ...]] = {
    "Otter AI": ("mcp_exists",),
    "Devin": ("mcp_exists",),
    "Consensus": ("auth_primary",),
    "NotebookLM": ("access_tier", "api_type"),
    "PitchBook": ("api_type", "access_tier"),
    "Twenty": ("business_type",),
    # Harvest, Paygent, systeme.io, Waterfall.io, Reducto, higgsfield, Grain: none
}

# Apps with extra seeded first-party domains
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
    """Atomic facts only. No verdict fields."""

    one_liner: str = ""
    business_type_confirmed: str = "no"  # yes | no
    docs_access: str = "unknown"
    docs_location: str = "none"
    auth_primary: str = "unknown"
    auth_secondary: list[str] = Field(default_factory=list)
    auth_detail: str = ""
    access_tier: str = "unknown"
    access_cost_note: str = ""
    api_type: str = "unknown"
    api_breadth: str = "unknown"
    has_openapi_spec: str = "unknown"
    needs_instance_url: str = "unknown"
    has_webhooks: str = "unknown"
    rate_limit_note: str = ""
    mcp_exists: str = "unknown"
    mcp_access: str = "n_a"
    evidence: dict[str, str] = Field(default_factory=dict)
    confidence: dict[str, str] = Field(default_factory=dict)
    notes: str = ""


def empty_unknown_row(app: dict[str, Any], *, flags: list[str] | None = None) -> dict[str, Any]:
    """Row with all atomic enums unknown (schema_fail / no docs path)."""
    evidence: dict[str, str] = {}
    confidence = {f: "low" for f in ATOMIC_ENUM_FIELDS}
    return {
        "app_name": app["app_name"],
        "category": app.get("category", ""),
        "one_liner": "",
        "business_type": "ai_native",  # overwritten by discover when available
        "business_type_confirmed": "no",
        "docs_access": "none_found",
        "docs_location": "none",
        "auth_primary": "unknown",
        "auth_secondary": [],
        "auth_detail": "",
        "access_tier": "unknown",
        "access_cost_note": "",
        "api_type": "unknown",
        "api_breadth": "unknown",
        "has_openapi_spec": "unknown",
        "needs_instance_url": "unknown",
        "has_webhooks": "unknown",
        "rate_limit_note": "",
        "mcp_exists": "unknown",
        "mcp_access": "n_a",
        "evidence": evidence,
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
    "docs_location": tuple(e.value for e in DocsLocation),
    "auth_primary": tuple(e.value for e in AuthScheme),
    "access_tier": tuple(e.value for e in AccessTier),
    "api_type": tuple(e.value for e in ApiType),
    "api_breadth": tuple(e.value for e in ApiBreadth),
    "has_openapi_spec": tuple(e.value for e in YesNoUnknown),
    "needs_instance_url": tuple(e.value for e in YesNoUnknown),
    "has_webhooks": tuple(e.value for e in YesNoUnknown),
    "mcp_exists": tuple(e.value for e in McpExists),
    "mcp_access": tuple(e.value for e in McpAccess),
    "buildability": tuple(e.value for e in Buildability),
    "blocker_type": tuple(e.value for e in BlockerType),
    "unblocker": tuple(e.value for e in Unblocker),
    "wait_class": tuple(e.value for e in WaitClass),
    "business_type_confirmed": ("yes", "no"),
}
