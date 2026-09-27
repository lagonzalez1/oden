"""
Firecrawl search adapters: map a Neo4j/Graph node into Firecrawl search params.

Edit QUERY_BY_TYPE when adding a new node label. Each builder owns which
fields matter and how they become a web-search query.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Literal, Optional, Protocol

from pydantic import Field

from Schema.base_schema import AppBaseModel


FirecrawlNodeLabel = Literal[
    "Transaction",
    "Asset",
    "Member",
    "Issuer",
    "Committee",
    "Derivative",
]

# Accept common FE / Neo4j casing variants → canonical label
_NODE_TYPE_ALIASES: Dict[str, FirecrawlNodeLabel] = {
    "transaction": "Transaction",
    "asset": "Asset",
    "member": "Member",
    "person": "Member",
    "issuer": "Issuer",
    "company": "Issuer",
    "organization": "Issuer",
    "committee": "Committee",
    "derivative": "Derivative",
    "calloption": "Derivative",
    "call_option": "Derivative",
}


class FireCrawlNodeTransform(AppBaseModel):
    """Normalized view of a graph node for Firecrawl."""

    node_type: FirecrawlNodeLabel
    content: dict[str, Any] = Field(default_factory=dict)


class FirecrawlSearchParams(AppBaseModel):
    """Args passed through to FirecrawlApp.search(...)."""

    query: str
    limit: int = 5
    scrape_options: Optional[dict[str, Any]] = Field(
        default_factory=lambda: {"formats": ["markdown"]}
    )


class FirecrawlPageResult(AppBaseModel):
    """Structured page extract returned by Firecrawl scrape JSON format."""

    title: str
    summary: str
    url: Optional[str] = None


class NodeQueryBuilder(Protocol):
    def __call__(self, content: dict[str, Any]) -> FirecrawlSearchParams: ...


def _join(*parts: Any) -> str:
    return " ".join(str(p).strip() for p in parts if p is not None and str(p).strip())


def _props(content: dict[str, Any]) -> dict[str, Any]:
    """Prefer nested GraphDTO `data`, else treat content as the property bag."""
    data = content.get("data")
    if isinstance(data, dict):
        return data
    return content


# ── Per-type builders ─────────────────────────────────────────────────────────

def build_transaction_query(content: dict[str, Any]) -> FirecrawlSearchParams:
    p = _props(content)
    ticker = p.get("ticker") or p.get("asset") or p.get("stock_ticker")
    tx_type = p.get("type") or p.get("transaction_type")
    date = p.get("transaction_date") or p.get("date") or p.get("notification_date")
    amount = p.get("amount") or p.get("amount_range")
    query = _join(
        ticker,
        "stock",
        tx_type,
        "congressional trade",
        date,
        amount,
        "news analysis",
    )
    return FirecrawlSearchParams(query=query or "congressional stock trade")


def build_asset_query(content: dict[str, Any]) -> FirecrawlSearchParams:
    p = _props(content)
    ticker = p.get("ticker") or p.get("stock_ticker")
    name = p.get("name") or p.get("asset_name")
    query = _join(ticker, name, "stock company news fundamentals")
    return FirecrawlSearchParams(query=query or "public company stock")


def build_member_query(content: dict[str, Any]) -> FirecrawlSearchParams:
    p = _props(content)
    name = (
        p.get("full_name")
        or p.get("official_full")
        or _join(p.get("first_name"), p.get("last_name"))
    )
    party = p.get("party")
    state = p.get("state")
    chamber = p.get("chamber")
    query = _join(
        name,
        party,
        state,
        chamber,
        "congress financial disclosure stock trades",
    )
    return FirecrawlSearchParams(query=query or "US congress member financial disclosure")


def build_issuer_query(content: dict[str, Any]) -> FirecrawlSearchParams:
    p = _props(content)
    name = p.get("name") or p.get("issuer_name")
    query = _join(name, "company SEC news")
    return FirecrawlSearchParams(query=query or "public company issuer")


def build_committee_query(content: dict[str, Any]) -> FirecrawlSearchParams:
    p = _props(content)
    name = p.get("name") or p.get("committee_name")
    chamber = p.get("chamber")
    query = _join(name, chamber, "US congress committee jurisdiction")
    return FirecrawlSearchParams(query=query or "US congress committee")


def build_derivative_query(content: dict[str, Any]) -> FirecrawlSearchParams:
    p = _props(content)
    ticker = p.get("ticker") or p.get("underlying")
    contract = p.get("contract_id")
    strike = p.get("strike")
    expiry = p.get("expiry") or p.get("expiration")
    query = _join(
        ticker,
        "options",
        contract,
        strike,
        expiry,
        "congressional derivative trade",
    )
    return FirecrawlSearchParams(query=query or "stock options trade")


QUERY_BY_TYPE: Dict[FirecrawlNodeLabel, NodeQueryBuilder] = {
    "Transaction": build_transaction_query,
    "Asset": build_asset_query,
    "Member": build_member_query,
    "Issuer": build_issuer_query,
    "Committee": build_committee_query,
    "Derivative": build_derivative_query,
}


# ── Public helpers ────────────────────────────────────────────────────────────

def normalize_node_type(node_type: str | None) -> FirecrawlNodeLabel:
    if not node_type or not str(node_type).strip():
        raise ValueError("node_type is required")
    raw = str(node_type).strip()
    if raw in QUERY_BY_TYPE:
        return raw  # type: ignore[return-value]
    alias = _NODE_TYPE_ALIASES.get(raw.lower())
    if alias:
        return alias
    raise ValueError(
        f"Unsupported node_type '{node_type}'. "
        f"Expected one of {list(QUERY_BY_TYPE)} "
        f"(or aliases {list(_NODE_TYPE_ALIASES)})"
    )


def transform_node(node: Any) -> FireCrawlNodeTransform:
    """
    Accept NodeDTO, dict, or similar.
    Expects either {type, data} or {node_type, content} / flat props.
    """
    if hasattr(node, "type") and hasattr(node, "data"):
        node_type = getattr(node, "type")
        content = getattr(node, "data") or {}
        if not isinstance(content, dict):
            content = {"value": content}
        return FireCrawlNodeTransform(
            node_type=normalize_node_type(node_type),
            content=content,
        )

    if isinstance(node, dict):
        node_type = node.get("type") or node.get("node_type") or node.get("label")
        content = node.get("data") or node.get("content") or node
        if not isinstance(content, dict):
            content = {"value": content}
        return FireCrawlNodeTransform(
            node_type=normalize_node_type(node_type),
            content=content,
        )

    raise TypeError(f"Cannot transform node of type {type(node)!r}")


def build_search_params(node: Any) -> FirecrawlSearchParams:
    """Look up the builder for this node type and return Firecrawl search kwargs."""
    transformed = transform_node(node)
    builder = QUERY_BY_TYPE[transformed.node_type] # Get the builder function 
    params = builder(transformed.content)
    if not params.query or not params.query.strip():
        raise ValueError(
            f"Empty search query for node_type={transformed.node_type}"
        )
    return params
