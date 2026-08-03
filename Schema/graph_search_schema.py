"""
Graph lookup / search adapter.

Mirrors the frontend LOOKUP_BY_TYPE + buildSearchParams contract so query
params stay configurable in one place when the UI filter set changes.

Frontend source of truth (JS):
  LOOKUP_TYPE_OPTIONS, LOOKUP_BY_TYPE, emptyFiltersFor, canSearchType, buildSearchParams
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Set

from pydantic import Field, field_validator, model_validator

from Schema.base_schema import AppBaseModel


LookupLabel = Literal["Asset", "Committee", "Issuer", "Member", "Transaction"]
LookupKind = Literal["preset", "filters"]
MemberSearchMode = Literal["name", "id"]
IssuerSearchMode = Literal["name", "id"]


# ── Registry (edit here when frontend filters change) ─────────────────────────

LOOKUP_TYPE_OPTIONS: List[LookupLabel] = [
    "Asset",
    "Committee",
    "Issuer",
    "Member",
    "Transaction",
]


@dataclass(frozen=True)
class LookupTypeConfig:
    """UI kind + which API filter keys this label accepts."""
    kind: LookupKind
    # Query-param names the frontend may send for this label (snake_case)
    filter_keys: Set[str] = field(default_factory=set)
    # Preset option values (e.g. Committee chamber)
    preset_options: tuple[str, ...] = ()
    identity: bool = False


LOOKUP_BY_TYPE: Dict[LookupLabel, LookupTypeConfig] = {
    "Committee": LookupTypeConfig(
        kind="preset",
        filter_keys={"chamber"},
        preset_options=("House", "Senate"),
    ),
    "Member": LookupTypeConfig(
        kind="filters",
        identity=True,
        filter_keys={
            "node_id",
            "first_name",
            "last_name",
            "party",
            "state",
            "chamber",
            "mode",
        },
    ),
    "Transaction": LookupTypeConfig(
        kind="filters",
        identity=False,
        filter_keys={
            "date_from",
            "date_to",
            "committee_relevance_score",
            "type",
        },
    ),
    "Asset": LookupTypeConfig(
        kind="filters",
        identity=False,
        filter_keys={"stock_ticker"},
    ),
    "Issuer": LookupTypeConfig(
        kind="filters",
        identity=True,
        filter_keys={"node_id", "name", "mode"},
    ),
}


# ── Request model ─────────────────────────────────────────────────────────────

class GraphSearchParams(AppBaseModel):
    """
    Unified search payload for GET /neo4j/node/{label}.

    All filter fields are optional; label selects which ones apply.
    Add new frontend filter keys here + to LOOKUP_BY_TYPE[label].filter_keys.
    """

    label: LookupLabel

    # Shared identity
    node_id: Optional[str] = None
    mode: Optional[Literal["name", "id"]] = None

    # Member
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    party: Optional[str] = None
    state: Optional[str] = None
    chamber: Optional[str] = None

    # Transaction
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    committee_relevance_score: Optional[float] = None
    type: Optional[str] = Field(
        default=None,
        description="Transaction type from UI e.g. Purchase | Sell (or P | S)",
    )

    # Asset
    stock_ticker: Optional[str] = None

    # Issuer
    name: Optional[str] = None

    @field_validator("state", "stock_ticker", mode="before")
    @classmethod
    def _upper_codes(cls, v: Any) -> Any:
        if isinstance(v, str) and v.strip():
            return v.strip().upper()
        return v

    @field_validator(
        "node_id",
        "first_name",
        "last_name",
        "party",
        "chamber",
        "date_from",
        "date_to",
        "type",
        "name",
        "mode",
        mode="before",
    )
    @classmethod
    def _empty_str_to_none(cls, v: Any) -> Any:
        if isinstance(v, str) and not v.strip():
            return None
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _validate_label_and_filters(self) -> "GraphSearchParams":
        if self.label not in LOOKUP_BY_TYPE:
            raise ValueError(f"Unsupported label: {self.label}")

        config = LOOKUP_BY_TYPE[self.label]
        # Drop keys that don't belong to this label (keep label itself)
        allowed = config.filter_keys | {"label"}
        for key in list(self.model_fields_set):
            if key not in allowed and key != "label":
                # Leave extras as None rather than error — forward-compatible
                setattr(self, key, None)

        if not self.can_search():
            raise ValueError(
                f"Insufficient filters for label={self.label}. "
                f"Accepted keys: {sorted(config.filter_keys)}"
            )
        return self

    def can_search(self) -> bool:
        """Mirror frontend canSearchType(label, filters)."""
        config = LOOKUP_BY_TYPE.get(self.label)
        if not config:
            return False

        # Presets (Committee) are searchable when a preset value is provided
        if config.kind == "preset":
            return bool(self.chamber and self.chamber in config.preset_options)

        if self.label == "Member":
            if self.mode == "id":
                return bool(self.node_id)
            has_name = bool(self.first_name or self.last_name)
            has_meta = bool(self.party or self.state or self.chamber)
            return has_name or has_meta or bool(self.node_id)

        if self.label == "Transaction":
            return bool(
                self.date_from
                or self.date_to
                or self.committee_relevance_score is not None
                or self.type
            )

        if self.label == "Asset":
            return bool(self.stock_ticker)

        if self.label == "Issuer":
            if self.mode == "id":
                return bool(self.node_id)
            return bool(self.name or self.node_id)

        return False

    def to_repo_filters(self) -> Dict[str, Any]:
        """
        Snake_case filter dict for the repository layer.
        Only includes non-null keys allowed for this label.
        """
        config = LOOKUP_BY_TYPE[self.label]
        data = self.model_dump(exclude_none=True)
        data.pop("label", None)
        data.pop("mode", None)  # UI-only; node_id / name already set
        return {k: v for k, v in data.items() if k in config.filter_keys and k != "mode"}


def empty_filters_for(label: LookupLabel) -> Dict[str, Any]:
    """Mirror frontend emptyFiltersFor — useful for docs/tests."""
    if label == "Member":
        return {
            "mode": "name",
            "first_name": None,
            "last_name": None,
            "node_id": None,
            "party": None,
            "state": None,
            "chamber": None,
        }
    if label == "Transaction":
        return {
            "date_from": None,
            "date_to": None,
            "committee_relevance_score": None,
            "type": None,
        }
    if label == "Asset":
        return {"stock_ticker": None}
    if label == "Issuer":
        return {"mode": "name", "node_id": None, "name": None}
    if label == "Committee":
        return {"chamber": None}
    return {}


# Type alias for service/repo handoff
GraphSearchFilters = Dict[str, Any]
