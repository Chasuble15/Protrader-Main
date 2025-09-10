# agent/actions/dispatcher.py
from typing import Callable, Dict, Any

from utils.logger import get_logger

logger = get_logger(__name__)

ActionFunc = Callable[[dict, str], dict]  # (args, cmd_id) -> payload à envoyer
_registry: Dict[str, ActionFunc] = {}


def register(name: str):
    def deco(fn: ActionFunc):
        logger.debug("Registering action '%s'", name)
        _registry[name] = fn
        return fn

    return deco


def dispatch(cmd: str, args: dict, cmd_id: str) -> dict:
    fn = _registry.get(cmd)
    if fn is None:
        # Réponse standard si commande inconnue
        from time import time as _now
        logger.warning("Unknown command '%s'", cmd)
        return {
            "type": "agent_info",
            "ts": int(_now()),
            "data": {"info": f"unknown command '{cmd}'"},
            "meta": {"command_id": cmd_id}
        }
    logger.info("Executing action '%s'", cmd)
    return fn(args, cmd_id)
