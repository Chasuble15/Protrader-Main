# agent/actions/config_actions.py
import time
from typing import Any, Dict

from actions.dispatcher import register
from settings import CONFIG_PATH
from utils.config_io import (
    load_config_yaml, safe_write_text, parse_yaml_to_dict, dict_to_yaml,
    validate_config_dict, validate_yaml_text, deep_merge
)
from utils.screenshot import grab_screenshot_base64  # <-- screenshot
from utils.logger import get_logger

logger = get_logger(__name__)


@register("get_config")
def get_config(args: Dict[str, Any], cmd_id: str) -> Dict[str, Any]:
    logger.info("Fetching configuration from %s", CONFIG_PATH)
    content = load_config_yaml(CONFIG_PATH)
    return {
        "type": "config",
        "ts": int(time.time()),
        "data": {"content": content},
        "meta": {"command_id": cmd_id, "path": str(CONFIG_PATH)}
    }

@register("validate_config")
def validate_config(args: Dict[str, Any], cmd_id: str) -> Dict[str, Any]:
    content = args.get("content", "")
    logger.info("Validating configuration")
    errs = validate_yaml_text(content)
    if errs:
        return {
            "type": "config_valid",
            "ts": int(time.time()),
            "data": {"ok": False, "error": "; ".join(errs)},
            "meta": {"command_id": cmd_id}
        }
    else:
        return {
            "type": "config_valid",
            "ts": int(time.time()),
            "data": {"ok": True},
            "meta": {"command_id": cmd_id}
        }

@register("set_config")
def set_config(args: Dict[str, Any], cmd_id: str) -> Dict[str, Any]:
    content = args.get("content", "")
    logger.info("Saving configuration to %s", CONFIG_PATH)
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Contenu YAML vide.")

    data = parse_yaml_to_dict(content)
    errs = validate_config_dict(data)
    if errs:
        raise ValueError("Config invalide: " + "; ".join(errs))

    safe_write_text(CONFIG_PATH, content)
    return {
        "type": "config_saved",
        "ts": int(time.time()),
        "data": {"ok": True},
        "meta": {"command_id": cmd_id, "path": str(CONFIG_PATH)}
    }

@register("patch_config")
def patch_config(args: Dict[str, Any], cmd_id: str) -> Dict[str, Any]:
    patch = args.get("patch", {})
    logger.info("Patching configuration at %s", CONFIG_PATH)
    if not isinstance(patch, dict):
        raise ValueError("patch doit être un mapping (dict).")

    current_text = load_config_yaml(CONFIG_PATH)
    current = parse_yaml_to_dict(current_text)
    merged = deep_merge(current, patch)

    errs = validate_config_dict(merged)
    if errs:
        raise ValueError("Config invalide après patch: " + "; ".join(errs))

    new_yaml = dict_to_yaml(merged)
    safe_write_text(CONFIG_PATH, new_yaml)
    return {
        "type": "config_saved",
        "ts": int(time.time()),
        "data": {"ok": True, "patched": True},
        "meta": {"command_id": cmd_id, "path": str(CONFIG_PATH)}
    }

@register("save_template")
def save_template(args: Dict[str, Any], cmd_id: str) -> Dict[str, Any]:
    name = args.get("name")
    filename = args.get("filename")  # ex: "btn_login.png"
    data_url = args.get("data_url")
    base_dir = args.get("base_dir", "./assets")
    logger.info("Saving template '%s' to %s", name, filename)

    if not (isinstance(name, str) and isinstance(filename, str) and isinstance(data_url, str)):
        raise ValueError("Paramètres invalides pour save_template")

    # decode data_url
    import base64, re
    m = re.match(r"^data:image/(png|jpeg);base64,(.+)$", data_url)
    if not m:
        raise ValueError("data_url invalide")
    b64 = m.group(2)
    raw = base64.b64decode(b64)

    from pathlib import Path
    out = Path(base_dir) / filename
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(raw)

    return {
        "type": "template_saved",
        "ts": int(time.time()),
        "data": {"ok": True, "path": str(out)},
        "meta": {"command_id": cmd_id, "name": name, "filename": filename}
    }

# ---------- SCREENSHOT ----------
@register("screenshot")
def screenshot(args: Dict[str, Any], cmd_id: str) -> Dict[str, Any]:
    """
    Args (optionnels):
      - monitor: int (par défaut 1)
      - region: [L, T, W, H] (facultatif)
      - format: "PNG" | "JPEG" (par défaut "PNG")
      - autres kwargs forwardés à grab_screenshot_base64 (ex: quality pour JPEG)
    """
    monitor = int(args.get("monitor", 1))
    region = args.get("region")
    if not (isinstance(region, (list, tuple)) and len(region) == 4):
        region = None
    fmt = args.get("format", "PNG")
    logger.info("Taking screenshot monitor=%s region=%s format=%s", monitor, region, fmt)

    extra = {k: v for k, v in args.items() if k not in {"monitor", "region", "format"}}

    data_url = grab_screenshot_base64(
        monitor_index=monitor,
        region=tuple(region) if region else None,
        fmt=fmt,
        **extra
    )

    return {
        "type": "screenshot",
        "ts": int(time.time()),
        "data": {"data_url": data_url},
        "meta": {"command_id": cmd_id, "monitor": monitor, "region": region, "format": fmt}
    }