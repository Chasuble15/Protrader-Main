# agent/handlers/commands.py
import time
from typing import Any, Dict

import bus
from actions.dispatcher import dispatch  # ← centralise les actions
from utils.logger import get_logger

logger = get_logger(__name__)

def _send(payload: Dict[str, Any]):
    if not bus.client:
        raise RuntimeError("client WS indisponible")
    bus.client.send(payload)

def on_message(msg: Dict[str, Any]):
    """
    Handler minimal : route vers le dispatcher d'actions,
    envoie le payload retourné.
    """
    logger.debug("Received message: %s", msg)
    if msg.get("type") != "command":
        logger.warning("Unhandled message type: %s", msg.get("type"))
        return

    cmd  = msg.get("cmd")
    args = msg.get("args") or {}
    cmd_id = msg.get("command_id")

    try:
        logger.info("Dispatching command '%s'", cmd)
        payload = dispatch(cmd, args, cmd_id)
        _send(payload)
    except Exception as e:
        logger.exception("Error while executing command '%s'", cmd)
        _send({
            "type": "agent_error",
            "ts": int(time.time()),
            "error": str(e),
            "meta": {"command_id": cmd_id, "cmd": cmd}
        })
