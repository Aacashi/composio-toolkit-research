"""Pure Python page cleaning. No LLM. No keyword matching."""

from __future__ import annotations

import re


LINK_ONLY_LINE = re.compile(r"^[\s\-]*(\[[^\]]+\]\([^)]+\)[\s,]*)+$")
CODE_FENCE = re.compile(r"```[\w]*\n.*?```", re.DOTALL)


def clean_page(markdown: str, max_chars: int = 10_000) -> tuple[str, bool]:
    """
    Returns (cleaned_text, thin_content_flag).
    Keep code blocks but cap each at 20 lines (LOGIC_FREEZE FIX 2).
    """
    text = _cap_code_blocks(markdown, max_lines=20)
    lines = []
    for line in text.splitlines():
        if LINK_ONLY_LINE.match(line.strip()):
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]
    thin = len(cleaned) < 500
    return cleaned, thin


def _cap_code_blocks(text: str, max_lines: int = 20) -> str:
    def repl(m: re.Match) -> str:
        block = m.group(0)
        lines = block.splitlines()
        if len(lines) <= max_lines + 2:  # fences + content
            return block
        # keep opening fence, first max_lines content lines, closing fence
        opening = lines[0]
        content = lines[1:-1][:max_lines]
        closing = lines[-1] if lines[-1].startswith("```") else "```"
        return "\n".join([opening, *content, closing])

    return CODE_FENCE.sub(repl, text)


def chunk_text(text: str, size: int = 15_000, max_chunks: int = 12) -> list[str]:
    if len(text) <= size:
        return [text]
    chunks = []
    for i in range(0, len(text), size):
        chunks.append(text[i : i + size])
        if len(chunks) >= max_chunks:
            break
    return chunks


PAGE_PRIORITY = (
    "auth",
    "pricing",
    "api_index",
    "openapi",
    "webhooks",
    "mcp",
)


def assemble_extract_input(
    pages: list[dict],
    *,
    total_cap: int = 40_000,
) -> str:
    """
    pages: list of {role, url, text} in any order.
    Fill in priority order up to total_cap.
    """
    by_role = {p["role"]: p for p in pages}
    parts: list[str] = []
    used = 0
    for role in PAGE_PRIORITY:
        p = by_role.get(role)
        if not p or not p.get("text"):
            continue
        header = f"=== SOURCE: {p['url']} ===\n"
        body = p["text"]
        remaining = total_cap - used - len(header)
        if remaining <= 0:
            break
        if len(body) > remaining:
            body = body[:remaining]
        parts.append(header + body)
        used += len(header) + len(body)
    return "\n\n".join(parts)
