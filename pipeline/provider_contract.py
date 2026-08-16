from __future__ import annotations

"""Shared contract for new official-source adapters.

Existing production adapters are intentionally not rewritten in bulk. New or
migrated adapters can implement this protocol incrementally while preserving the
canonical Tender Engine evidence model.
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Protocol


@dataclass(slots=True)
class ProviderHealth:
    provider: str
    status: str
    observed_at: str
    latency_ms: int | None = None
    http_status: int | None = None
    rate_limited: bool = False
    auth_required: bool = False
    captcha_required: bool = False
    error: str | None = None


@dataclass(slots=True)
class ProviderObservation:
    provider: str
    source_id: str
    source_url: str | None
    observed_at: str
    raw_hash: str | None = None
    grain: str = "NOTICE_FIRST_TENDER"
    notice: dict[str, Any] = field(default_factory=dict)
    procedure: dict[str, Any] = field(default_factory=dict)
    lots: list[dict[str, Any]] = field(default_factory=list)
    buyers: list[dict[str, Any]] = field(default_factory=list)
    suppliers: list[dict[str, Any]] = field(default_factory=list)
    awards: list[dict[str, Any]] = field(default_factory=list)
    documents: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    route_status: str = "UNKNOWN"

    def as_record(self) -> dict[str, Any]:
        return asdict(self)


class ProcurementProvider(Protocol):
    """Target interface for provider adapters.

    Methods may be implemented by API, bulk export, feed, or public HTTP adapters.
    Access barriers must be returned as explicit health/route states rather than
    bypassed or converted to empty results.
    """

    name: str

    def healthcheck(self) -> ProviderHealth: ...

    def discover(self, **kwargs: Any) -> Iterable[ProviderObservation]: ...

    def fetch_detail(self, source_id: str) -> ProviderObservation: ...

    def fetch_documents(self, source_id: str) -> list[dict[str, Any]]: ...

    def checkpoint(self) -> dict[str, Any]: ...
