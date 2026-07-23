# Definitions (AMENDMENT_3)

Closed enums and stated assumptions. Supersedes older SPEC/LOGIC_FREEZE field lists.

---

## Stated assumption: public / distributed app path

Composio ships toolkits to many customers. Verdicts assume the **public / distributed** path, not a single-tenant custom app. Vendor app review → `access_tier=approval_gated` / buildability `needs_review`.

## CLI-only tools are not connector candidates

`api_type=cli_only` = local command, no vendor API (Mermaid CLI, Sherlock). Not connector candidates.

## `none` vs `unknown`

- **none** — checked; genuinely does not exist  
- **unknown** — could not determine  

Never collapse these.

---

## Gemini facts (10)

| field | values |
|---|---|
| `business_type` | infra_usage_based · saas_seat_based · ad_platform · data_vendor · commerce_platform · enterprise_sales · ai_native |
| `docs_access` | public · login_required · on_request · none_found |
| `access_tier` | open · self_serve_free · self_serve_trial · card_required · plan_gated · approval_gated · partner_gated · no_public_access |

`access_tier` notes: **open** = no account and no credentials required at all. **self_serve_free** = free signup required, no card, credentials in minutes. “No setup fees” / pay-as-you-go with signup required is **self_serve_free**, not open.
| `auth_primary` | api_key · pat · oauth2 · oauth1 · basic · jwt_keypair · hmac_signed · aws_sigv4 · session_only · none · unknown |
| `api_type` | rest · graphql · both · cli_only · none · unknown |
| `mcp_exists` | official_open · official_gated · community · none · unknown |
| `has_openapi_spec` | yes · no · unknown |
| `needs_instance_url` | yes · no · unknown |
| `has_webhooks` | yes · no · unknown |
| `is_open_source` | yes · no · unknown |

`business_type` is Call 1 prior; Call 2 must not overwrite it. If pages do not support the prior, raise flag `business_type_unconfirmed`.

## Free text (4)

`one_liner`, `auth_detail`, `access_cost_note`, `notes`

## Stage 2 derived (5)

| field | values |
|---|---|
| `access_tier_rollup` | open ← {open,self_serve_free,self_serve_trial}; paid ← {card_required,plan_gated}; gated ← {approval_gated,partner_gated,no_public_access} |
| `buildability` | easy_win · easy_but_paid · needs_review · needs_outreach · blocked · unknown |
| `blocker_type` | none · payment · vendor_review · partnership · no_api · no_docs · unknown |
| `unblocker` | nobody · composio_finance · vendor_human · composio_bd · n_a |
| `blocker` | one-line string from derive_verdict; empty when easy_win |

## Audit

`app_name`, `category`, `run_id`, `evidence{}`, `confidence{}`, `flags[]`, `sources_fetched[]`, `first_party_domains[]`

Flags include: unsourced · thin_content · no_docs_found · schema_fail · chunked · retry_used · hint_unconfirmed · second_round_used · business_type_unconfirmed · unsupported_absence

## Post-run cross-check

`composio_supports` yes|no · `composio_auth_scheme` · `agrees_with_composio` yes|disagrees|n_a
