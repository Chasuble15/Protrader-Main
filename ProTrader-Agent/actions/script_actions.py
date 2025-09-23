# actions/script_actions.py - actions liées au lancement du script ProTrader
import time
import threading
from typing import Any, Dict
import base64, tempfile
from pathlib import Path
import yaml

from settings import CONFIG_PATH

from actions.dispatcher import register
from scripts.login import run
from utils.logger import get_logger

logger = get_logger(__name__)


def _resolve_temp_dir() -> Path:
    """Return directory to store temporary image files."""
    default_dir = Path.home() / "AppData/Local/Temp"
    try:
        if CONFIG_PATH.exists():
            data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
            cfg_dir = data.get("temp_dir")
            if isinstance(cfg_dir, str) and cfg_dir.strip():
                return Path(cfg_dir).expanduser()
    except Exception as exc:  # pragma: no cover - best effort
        logger.debug("Failed to read temp_dir from config: %s", exc)
    return default_dir

@register("start_script")
def start_script(args: Dict[str, Any], cmd_id: str) -> Dict[str, Any]:
    items = (args or {}).get("items") or []
    fortune_lines = (args or {}).get("fortune_lines") or []
    logger.info(
        "start_script called with %d item(s) and %d fortune line(s)",
        len(items),
        len(fortune_lines),
    )
    if fortune_lines:
        logger.info("fortune lines: %s", fortune_lines)
    if not items:
        return {
            "type": "script_result",
            "ts": int(time.time()),
            "data": {"ok": False, "error": "Aucun item reçu"},
            "meta": {"command_id": cmd_id, "cmd": "start_script"},
        }

    temp_dir = _resolve_temp_dir()
    temp_dir.mkdir(parents=True, exist_ok=True)

    resources = []
    for it in items:
        # slug prioritaire: "slug" ou "slug_fr", sinon fallback name_fr
        slug = (it.get("slug") or it.get("slug_fr") or it.get("name_fr") or "").strip()

        img_b64 = it.get("img_blob") or it.get("img_base64")
        if not img_b64:
            logger.warning("Item without image skipped: %s", slug)
            continue

        # Décode et sauvegarde en PNG temporaire (toujours PNG d’après ta contrainte)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png", dir=temp_dir)
        tmp.write(base64.b64decode(img_b64))
        tmp.flush()
        tmp.close()

        template_path = str(temp_dir / Path(tmp.name).name)
        resources.append({"slug": slug, "template_path": template_path})

    if not resources:
        return {
            "type": "script_result",
            "ts": int(time.time()),
            "data": {"ok": False, "error": "Aucune ressource exploitable"},
            "meta": {"command_id": cmd_id, "cmd": "start_script"},
        }

    # Lance le FSM avec la liste complète des ressources
    logger.info("Launching script thread with %d resource(s)", len(resources))
    threading.Thread(target=run, args=(resources, fortune_lines), daemon=True).start()

    return {
        "type": "script_result",
        "ts": int(time.time()),
        "data": {"ok": True, "resources": resources},
        "meta": {"command_id": cmd_id, "cmd": "start_script"},
    }
