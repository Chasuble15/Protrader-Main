"""Context helpers used by the marketplace FSM."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:  # pragma: no cover - optional dependency at runtime
    import mss  # type: ignore
except Exception:  # pragma: no cover - fallback when mss is unavailable
    mss = None  # type: ignore

from utils.logger import get_logger

from .config import MONITOR_INDEX

logger = get_logger(__name__)

ScreenRegion = Optional[Tuple[int, int, int, int]]


@dataclass
class MarketplaceContext:
    """Encapsulates the mutable data shared across FSM states."""

    resources: Sequence[Dict[str, Any]]
    fortune_lines: Sequence[Dict[str, Any]] = field(default_factory=list)
    fortune_lookup: Dict[str, Dict[str, Dict[str, Any]]] = field(default_factory=dict)
    resource_index: int = 0
    slug: str = ""
    template_path: str = ""
    pending_purchase: Optional[Dict[str, Any]] = None
    reset_scan: bool = True
    targets: List[Tuple[str, str]] = field(default_factory=list)
    scanned: Dict[str, Optional[int]] = field(default_factory=dict)
    attempts: Dict[str, int] = field(default_factory=dict)
    completed_purchases: List[Dict[str, Any]] = field(default_factory=list)
    current_sale: Optional[Dict[str, Any]] = None
    current_kamas: Optional[int] = None
    right_half_region: ScreenRegion = None
    skip_recherche_click: bool = False


def _build_fortune_lookup(fortune_lines: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Return a lookup dictionary indexed by slug then quantity label."""

    lookup: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for line in fortune_lines or []:
        slug = (line.get("slug") or "").strip().lower()
        qty = (line.get("qty") or "").strip()
        if slug and qty:
            lookup.setdefault(slug, {})[qty] = line
    return lookup


def get_fortune_line(ctx: MarketplaceContext, slug: str, qty: str) -> Optional[Dict[str, Any]]:
    """Lookup a fortune line within the context."""

    slug_key = (slug or "").strip().lower()
    if not slug_key:
        return None
    return (ctx.fortune_lookup or {}).get(slug_key, {}).get(qty)


def compute_right_half_region(monitor_index: int = MONITOR_INDEX) -> ScreenRegion:
    """Return the bounding box describing the right half of the selected monitor."""

    monitor_idx = int(monitor_index or 1)
    if mss is None:
        logger.debug("Bibliothèque mss indisponible, aucune région écran déterminée")
        return None
    try:
        with mss.mss() as sct:
            monitors = sct.monitors
            if monitor_idx < 1 or monitor_idx >= len(monitors):
                monitor_idx = 1
            mon = monitors[monitor_idx]
            width = int(mon.get("width", 0))
            height = int(mon.get("height", 0))
    except Exception as exc:  # pragma: no cover - best effort logging only
        logger.debug("Impossible de déterminer la moitié droite de l'écran: %s", exc)
        return None

    if width <= 0 or height <= 0:
        return None

    half_width = width // 2
    return (half_width, 0, width - half_width, height)


def create_context(
    resources: Sequence[Dict[str, Any]],
    fortune_lines: Optional[Sequence[Dict[str, Any]]] = None,
    monitor_index: int = MONITOR_INDEX,
) -> MarketplaceContext:
    """Create and initialise the FSM context for the marketplace workflow."""

    lines = fortune_lines or []
    return MarketplaceContext(
        resources=resources,
        fortune_lines=lines,
        fortune_lookup=_build_fortune_lookup(lines),
        resource_index=0,
        slug="",
        template_path="",
        pending_purchase=None,
        reset_scan=True,
        targets=[],
        scanned={},
        attempts={},
        completed_purchases=[],
        current_sale=None,
        current_kamas=None,
        right_half_region=compute_right_half_region(monitor_index),
        skip_recherche_click=False,
    )


__all__ = [
    "MarketplaceContext",
    "_build_fortune_lookup",
    "get_fortune_line",
    "compute_right_half_region",
    "create_context",
]
