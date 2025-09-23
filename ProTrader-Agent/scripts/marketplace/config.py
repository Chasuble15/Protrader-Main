"""Configuration helpers for the marketplace workflow."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Sequence

from settings import CONFIG_PATH
from utils.config_io import load_config_yaml, parse_yaml_to_dict
from utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_SALE_QTY_ORDER: Sequence[str] = ("x1", "x10", "x100", "x1000")
DEFAULT_SCAN_MAX_ATTEMPTS_PER_QTY = 5
DEFAULT_CLIC_ACHAT_OFFSET_PX = 100
DEFAULT_VENTE_CLICK_MAX_ATTEMPTS = 6
DEFAULT_VENTE_FALLBACK_REGION_RATIO = 0.28
DEFAULT_VENTE_FALLBACK_OFFSET_PX = 240
DEFAULT_PURCHASE_MAX_RETRIES = 5
DEFAULT_KAMAS_CHECK_MAX_ATTEMPTS = 10
DEFAULT_TICK_HZ = 2


@dataclass(frozen=True)
class MarketplaceConfig:
    """Container for resolved marketplace configuration values."""

    base_dir: Path
    btn_jouer_path: Path
    est_en_jeu_path: Path
    ouvrir_hdv_path: Path
    attente_hdv_path: Path
    qte_x1_path: Path
    qte_x10_path: Path
    qte_x100_path: Path
    qte_x1000_path: Path
    recherche_path: Path
    kamas_path: Path
    onglet_achat_path: Path
    onglet_vente_path: Path
    sel_vente_paths: Dict[str, Path]
    vente_paths: Dict[str, Path]
    confirmer_achat_path: Optional[Path]
    sale_qty_order: Sequence[str]
    scan_max_attempts_per_qty: int
    clic_achat_offset_px: int
    vente_click_max_attempts: int
    vente_fallback_region_ratio: float
    vente_fallback_offset_px: int
    purchase_max_retries: int
    kamas_check_max_attempts: int
    monitor_index: int
    tick_hz: int


def _resolve_template(base_dir: Path, templates: Dict[str, str], key: str) -> Path:
    value = templates.get(key)
    if not value:
        raise KeyError(f"Template '{key}' introuvable dans la configuration")
    return (base_dir / value).expanduser()


def _resolve_optional_template(
    base_dir: Path, templates: Dict[str, str], key: str
) -> Optional[Path]:
    value = templates.get(key)
    if not value:
        return None
    path = (base_dir / value).expanduser()
    if not path.exists():
        logger.warning("Template %s introuvable: %s", key, path)
        return None
    return path


def _resolve_group(
    base_dir: Path, templates: Dict[str, str], prefix: str, labels: Sequence[str]
) -> Dict[str, Path]:
    resolved: Dict[str, Path] = {}
    for label in labels:
        key = f"{prefix}_{label}"
        resolved[label] = _resolve_template(base_dir, templates, key)
    return resolved


@lru_cache(maxsize=1)
def load_marketplace_config() -> MarketplaceConfig:
    """Load and resolve the marketplace configuration file."""

    raw_config = parse_yaml_to_dict(load_config_yaml(CONFIG_PATH))
    base_dir = Path(raw_config.get("base_dir") or ".").expanduser()
    templates: Dict[str, str] = raw_config.get("templates", {}) or {}

    sale_qty_order = tuple(raw_config.get("sale_qty_order") or DEFAULT_SALE_QTY_ORDER)

    settings_section = raw_config.get("settings", {}) or {}
    monitor_index = int(settings_section.get("monitor_index", 1) or 1)

    return MarketplaceConfig(
        base_dir=base_dir,
        btn_jouer_path=_resolve_template(base_dir, templates, "btn_jouer"),
        est_en_jeu_path=_resolve_template(base_dir, templates, "est_en_jeu"),
        ouvrir_hdv_path=_resolve_template(base_dir, templates, "ouvrir_hdv"),
        attente_hdv_path=_resolve_template(base_dir, templates, "attente_hdv"),
        qte_x1_path=_resolve_template(base_dir, templates, "qte_x1"),
        qte_x10_path=_resolve_template(base_dir, templates, "qte_x10"),
        qte_x100_path=_resolve_template(base_dir, templates, "qte_x100"),
        qte_x1000_path=_resolve_template(base_dir, templates, "qte_x1000"),
        recherche_path=_resolve_template(base_dir, templates, "recherche"),
        kamas_path=_resolve_template(base_dir, templates, "kamas"),
        onglet_achat_path=_resolve_template(base_dir, templates, "onglet_achat"),
        onglet_vente_path=_resolve_template(base_dir, templates, "onglet_vente"),
        sel_vente_paths=_resolve_group(
            base_dir, templates, "sel_vente", sale_qty_order
        ),
        vente_paths=_resolve_group(base_dir, templates, "vente", sale_qty_order),
        confirmer_achat_path=_resolve_optional_template(
            base_dir, templates, "confirmer_achat"
        ),
        sale_qty_order=sale_qty_order,
        scan_max_attempts_per_qty=int(
            raw_config.get("scan_max_attempts_per_qty", DEFAULT_SCAN_MAX_ATTEMPTS_PER_QTY)
        ),
        clic_achat_offset_px=int(
            raw_config.get("clic_achat_offset_px", DEFAULT_CLIC_ACHAT_OFFSET_PX)
        ),
        vente_click_max_attempts=int(
            raw_config.get("vente_click_max_attempts", DEFAULT_VENTE_CLICK_MAX_ATTEMPTS)
        ),
        vente_fallback_region_ratio=float(
            raw_config.get(
                "vente_fallback_region_ratio", DEFAULT_VENTE_FALLBACK_REGION_RATIO
            )
        ),
        vente_fallback_offset_px=int(
            raw_config.get("vente_fallback_offset_px", DEFAULT_VENTE_FALLBACK_OFFSET_PX)
        ),
        purchase_max_retries=int(
            raw_config.get("purchase_max_retries", DEFAULT_PURCHASE_MAX_RETRIES)
        ),
        kamas_check_max_attempts=int(
            raw_config.get("kamas_check_max_attempts", DEFAULT_KAMAS_CHECK_MAX_ATTEMPTS)
        ),
        monitor_index=monitor_index,
        tick_hz=int(raw_config.get("tick_hz", DEFAULT_TICK_HZ)),
    )


CONFIG = load_marketplace_config()

BTN_JOUER_PATH = CONFIG.btn_jouer_path
EST_EN_JEU_PATH = CONFIG.est_en_jeu_path
OUVRIR_HDV_PATH = CONFIG.ouvrir_hdv_path
ATTENTE_HDV_PATH = CONFIG.attente_hdv_path
QTE_X1_PATH = CONFIG.qte_x1_path
QTE_X10_PATH = CONFIG.qte_x10_path
QTE_X100_PATH = CONFIG.qte_x100_path
QTE_X1000_PATH = CONFIG.qte_x1000_path
RECHERCHE_PATH = CONFIG.recherche_path
KAMAS_PATH = CONFIG.kamas_path
ONGLET_ACHAT_PATH = CONFIG.onglet_achat_path
ONGLET_VENTE_PATH = CONFIG.onglet_vente_path
SEL_VENTE_PATHS = CONFIG.sel_vente_paths
VENTE_PATHS = CONFIG.vente_paths
CONFIRMER_ACHAT_PATH = CONFIG.confirmer_achat_path
SALE_QTY_ORDER = CONFIG.sale_qty_order
SCAN_MAX_ATTEMPTS_PER_QTY = CONFIG.scan_max_attempts_per_qty
CLIC_ACHAT_OFFSET_PX = CONFIG.clic_achat_offset_px
VENTE_CLICK_MAX_ATTEMPTS = CONFIG.vente_click_max_attempts
VENTE_FALLBACK_REGION_RATIO = CONFIG.vente_fallback_region_ratio
VENTE_FALLBACK_OFFSET_PX = CONFIG.vente_fallback_offset_px
PURCHASE_MAX_RETRIES = CONFIG.purchase_max_retries
KAMAS_CHECK_MAX_ATTEMPTS = CONFIG.kamas_check_max_attempts
MONITOR_INDEX = CONFIG.monitor_index
TICK_HZ = CONFIG.tick_hz

__all__ = [
    "CONFIG",
    "BTN_JOUER_PATH",
    "EST_EN_JEU_PATH",
    "OUVRIR_HDV_PATH",
    "ATTENTE_HDV_PATH",
    "QTE_X1_PATH",
    "QTE_X10_PATH",
    "QTE_X100_PATH",
    "QTE_X1000_PATH",
    "RECHERCHE_PATH",
    "KAMAS_PATH",
    "ONGLET_ACHAT_PATH",
    "ONGLET_VENTE_PATH",
    "SEL_VENTE_PATHS",
    "VENTE_PATHS",
    "CONFIRMER_ACHAT_PATH",
    "SALE_QTY_ORDER",
    "SCAN_MAX_ATTEMPTS_PER_QTY",
    "CLIC_ACHAT_OFFSET_PX",
    "VENTE_CLICK_MAX_ATTEMPTS",
    "VENTE_FALLBACK_REGION_RATIO",
    "VENTE_FALLBACK_OFFSET_PX",
    "PURCHASE_MAX_RETRIES",
    "KAMAS_CHECK_MAX_ATTEMPTS",
    "MONITOR_INDEX",
    "TICK_HZ",
    "load_marketplace_config",
    "MarketplaceConfig",
]
