# agent/utils/config_io.py
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List

import yaml
from utils.logger import get_logger

logger = get_logger(__name__)

# ---------- I/O ----------
def _ensure_parent_exists(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)

def safe_read_text(p: Path) -> str:
    if not p.exists():
        logger.warning("File %s does not exist", p)
        return ""
    logger.info("Reading text from %s", p)
    return p.read_text(encoding="utf-8")

def safe_write_text(p: Path, content: str):
    _ensure_parent_exists(p)
    if p.exists():
        bak = p.with_suffix(p.suffix + ".bak")
        bak.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
        logger.info("Backup created for %s", p)
    logger.info("Writing text to %s", p)
    p.write_text(content, encoding="utf-8")

# ---------- Merge ----------
def deep_merge(dst: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(dst)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out

# ---------- Validation "maison" ----------
def _is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)

def _is_float(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def validate_config_dict(data: Any) -> List[str]:
    errs: List[str] = []
    if not isinstance(data, dict):
        return ["Le YAML racine doit être un mapping (dict)."]

    # base_dir
    if "base_dir" in data and not isinstance(data["base_dir"], str):
        errs.append("base_dir doit être une chaîne.")

    # click_points
    cp = data.get("click_points", {})
    if cp and not isinstance(cp, dict):
        errs.append("click_points doit être un mapping de points.")
    else:
        for name, point in cp.items() if isinstance(cp, dict) else []:
            if not isinstance(point, dict):
                errs.append(f"click_points.{name} doit être un mapping.")
                continue
            x, y = point.get("x"), point.get("y")
            if not _is_int(x) or not _is_int(y):
                errs.append(f"click_points.{name}.x/y doivent être des entiers.")
            jit = point.get("jitter", 5)
            if not _is_int(jit) or jit < 0:
                errs.append(f"click_points.{name}.jitter doit être un entier >= 0.")

    # ocr_zones
    oz = data.get("ocr_zones", {})
    if oz and not isinstance(oz, dict):
        errs.append("ocr_zones doit être un mapping de rectangles.")
    else:
        for name, rect in oz.items() if isinstance(oz, dict) else []:
            if not (isinstance(rect, (list, tuple)) and len(rect) == 4 and all(_is_int(v) for v in rect)):
                errs.append(f"ocr_zones.{name} doit être [left, top, width, height] (entiers).")
                continue
            _, _, w, h = rect
            if w <= 0 or h <= 0:
                errs.append(f"ocr_zones.{name}.width/height doivent être > 0.")

    # templates
    tm = data.get("templates", {})
    if tm and not isinstance(tm, dict):
        errs.append("templates doit être un mapping de chemins.")
    else:
        for name, path in tm.items() if isinstance(tm, dict) else []:
            if not isinstance(path, str) or not path:
                errs.append(f"templates.{name} doit être une chaîne non vide.")

    # settings
    st = data.get("settings", {})
    if st and not isinstance(st, dict):
        errs.append("settings doit être un mapping.")
    else:
        mi = st.get("monitor_index", 1) if isinstance(st, dict) else 1
        if not _is_int(mi) or mi < 1:
            errs.append("settings.monitor_index doit être un entier >= 1.")
        dt = st.get("default_threshold", 0.88) if isinstance(st, dict) else 0.88
        if not _is_float(dt) or not (0 <= float(dt) <= 1):
            errs.append("settings.default_threshold doit être un nombre entre 0 et 1.")
        th = st.get("thresholds", {}) if isinstance(st, dict) else {}
        if th and not isinstance(th, dict):
            errs.append("settings.thresholds doit être un mapping.")
        else:
            for k, v in th.items() if isinstance(th, dict) else []:
                if not _is_float(v) or not (0 <= float(v) <= 1):
                    errs.append(f"settings.thresholds.{k} doit être un nombre entre 0 et 1.")
    return errs

# ---------- Helpers haut niveau ----------
def load_config_yaml(path: Path) -> str:
    return safe_read_text(path)

def parse_yaml_to_dict(text: str) -> Dict[str, Any]:
    return yaml.safe_load(text) or {}

def dict_to_yaml(data: Dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)

def validate_yaml_text(text: str) -> List[str]:
    try:
        data = parse_yaml_to_dict(text)
    except Exception as ye:
        return [f"YAML error: {ye}"]
    return validate_config_dict(data)
