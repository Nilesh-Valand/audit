from __future__ import annotations

from typing import Any


REQUIRED_FIELDS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "Product": ("name",),
    "Article": ("headline",),
    "NewsArticle": ("headline",),
    "BlogPosting": ("headline",),
    "Organization": ("name",),
}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _types_of(node: dict[str, Any]) -> list[str]:
    raw = node.get("@type")
    types: list[str] = []
    for item in _as_list(raw):
        if isinstance(item, str) and item.strip():
            # Accept schema.org URLs or bare names.
            types.append(item.strip().split("/")[-1])
    return types


def _has_field(node: dict[str, Any], field: str) -> bool:
    value = node.get(field)
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float, bool)):
        return True
    if isinstance(value, dict):
        return bool(value)
    if isinstance(value, list):
        return len(value) > 0
    return True


def _iter_graph_nodes(payload: Any) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if "@graph" in value:
                for item in _as_list(value.get("@graph")):
                    walk(item)
            else:
                nodes.append(value)
            # Also walk nested typed objects lightly? Keep top-level + @graph only.
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return nodes


def schema_blocks_have_type(blocks: list[Any], type_name: str) -> bool:
    """True if any JSON-LD block declares the given @type (e.g. Organization, WebSite)."""
    wanted = type_name.strip().split("/")[-1].lower()
    if not wanted:
        return False
    for block in blocks:
        if not isinstance(block, dict):
            continue
        parsed = block.get("parsed")
        if parsed is None:
            continue
        for node in _iter_graph_nodes(parsed):
            for node_type in _types_of(node):
                if node_type.lower() == wanted:
                    return True
    return False


def validate_schema_blocks(blocks: list[dict[str, Any]]) -> list[str]:
    """
    Return human-readable problems for stored schema blocks.
    Each block: {raw, parsed, parse_error?}.
    """
    problems: list[str] = []
    validated_types = set(REQUIRED_FIELDS_BY_TYPE)

    for index, block in enumerate(blocks, start=1):
        if not isinstance(block, dict):
            continue
        if block.get("parse_error") or block.get("parsed") is None:
            problems.append(f"Schema block #{index} is malformed JSON-LD.")
            continue

        parsed = block.get("parsed")
        for node in _iter_graph_nodes(parsed):
            for type_name in _types_of(node):
                if type_name not in validated_types:
                    continue
                # Article family can use name as headline fallback.
                required = REQUIRED_FIELDS_BY_TYPE[type_name]
                missing = []
                for field in required:
                    if _has_field(node, field):
                        continue
                    if type_name in {"Article", "NewsArticle", "BlogPosting"} and field == "headline":
                        if _has_field(node, "name"):
                            continue
                    missing.append(field)
                if missing:
                    problems.append(
                        f"{type_name} schema is missing required field(s): {', '.join(missing)}."
                    )

    return problems
