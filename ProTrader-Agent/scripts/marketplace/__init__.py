"""Marketplace workflow package."""
from __future__ import annotations

import os
import time
from typing import Optional, Sequence, TYPE_CHECKING

from utils.fsm import FSM, StateDef
from utils.logger import get_logger
from utils.misc import close_dofus, open_dofus

from .config import (
    ATTENTE_HDV_PATH,
    BTN_JOUER_PATH,
    EST_EN_JEU_PATH,
    MONITOR_INDEX,
    OUVRIR_HDV_PATH,
    RECHERCHE_PATH,
    TICK_HZ,
)
from .context import create_context
from .purchase import PURCHASE_STATES, _try_read_kamas_amount
from .sale import SALE_STATES
from .telemetry import _send_kamas, _send_state

logger = get_logger(__name__)

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from utils.mouse import move_click as MoveClickFn
    from utils.vision import find_template_on_screen as FindTemplateFn

_move_click_impl = None
_find_template_impl = None


def _ensure_mouse():
    global _move_click_impl
    if _move_click_impl is None:
        from utils.mouse import move_click as mc

        _move_click_impl = mc
    return _move_click_impl


def _ensure_vision():
    global _find_template_impl
    if _find_template_impl is None:
        from utils.vision import find_template_on_screen as finder

        _find_template_impl = finder
    return _find_template_impl


def on_enter_lancement(fsm):
    _send_state("LANCEMENT")
    open_dofus()


def on_tick_lancement(fsm):
    find_template_on_screen = _ensure_vision()
    res = find_template_on_screen(
        template_path=str(BTN_JOUER_PATH),
        debug=True,
    )

    if res:
        time.sleep(1)
        move_click = _ensure_mouse()
        move_click(res.center[0], res.center[1])
        return "ATTENTE_CONNEXION"


def on_enter_attente_connexion(fsm):
    _send_state("ATTENTE_CONNEXION")


def on_tick_attente_connexion(fsm):
    find_template_on_screen = _ensure_vision()
    res = find_template_on_screen(
        template_path=str(EST_EN_JEU_PATH),
        debug=True,
    )

    if res:
        time.sleep(1)
        return "EN_JEU"


def on_enter_en_jeu(fsm):
    _send_state("EN_JEU")
    return "OUVRIR_HDV"


def on_enter_ouvrir_hdv(fsm):
    _send_state("OUVRIR_HDV")


def on_tick_ouvrir_hdv(fsm):
    find_template_on_screen = _ensure_vision()
    res = find_template_on_screen(
        template_path=str(OUVRIR_HDV_PATH),
        debug=True,
    )

    if res:
        time.sleep(1)
        move_click = _ensure_mouse()
        move_click(res.center[0], res.center[1])
        return "ATTENTE_HDV"


def on_enter_attente_hdv(fsm):
    _send_state("ATTENTE_HDV")


def on_tick_attente_hdv(fsm):
    find_template_on_screen = _ensure_vision()
    res = find_template_on_screen(
        template_path=str(ATTENTE_HDV_PATH),
        debug=True,
    )

    if res:
        time.sleep(1)
        return "GET_KAMAS"


def on_enter_get_kamas(fsm):
    _send_state("GET_KAMAS")


def on_tick_get_kamas(fsm):
    kamas_value = _try_read_kamas_amount()

    if kamas_value is not None:
        fsm.ctx.current_kamas = kamas_value
        logger.info("Fortune actuelle : %d K", kamas_value)
        _send_kamas(kamas_value)
        return "ENTRER_RESSOURCE"


def on_enter_clic_recherche(fsm):
    _send_state("CLIC_RECHERCHE")


def on_tick_clic_recherche(fsm):
    if getattr(fsm.ctx, "skip_recherche_click", False):
        fsm.ctx.skip_recherche_click = False
        time.sleep(0.5)
        fsm.ctx.resource_index += 1
        if fsm.ctx.resource_index < len(fsm.ctx.resources):
            return "ENTRER_RESSOURCE"
        return "END"

    find_template_on_screen = _ensure_vision()
    res = find_template_on_screen(
        template_path=str(RECHERCHE_PATH),
        debug=True,
    )

    if res:
        time.sleep(1)
        move_click = _ensure_mouse()
        move_click(res.center[0], res.center[1])
        time.sleep(1)
        fsm.ctx.resource_index += 1
        if fsm.ctx.resource_index < len(fsm.ctx.resources):
            return "ENTRER_RESSOURCE"
        return "END"


def on_enter_end(fsm):
    _send_state("END")
    close_dofus()
    if os.name == "nt":
        os.system("shutdown /s /t 0")
    else:
        os.system("shutdown -h now")


COMMON_STATES = {
    "LANCEMENT": StateDef("LANCEMENT", on_enter=on_enter_lancement, on_tick=on_tick_lancement),
    "ATTENTE_CONNEXION": StateDef(
        "ATTENTE_CONNEXION", on_enter=on_enter_attente_connexion, on_tick=on_tick_attente_connexion
    ),
    "EN_JEU": StateDef("EN_JEU", on_enter=on_enter_en_jeu),
    "OUVRIR_HDV": StateDef("OUVRIR_HDV", on_enter=on_enter_ouvrir_hdv, on_tick=on_tick_ouvrir_hdv),
    "ATTENTE_HDV": StateDef("ATTENTE_HDV", on_enter=on_enter_attente_hdv, on_tick=on_tick_attente_hdv),
    "GET_KAMAS": StateDef("GET_KAMAS", on_enter=on_enter_get_kamas, on_tick=on_tick_get_kamas),
    "CLIC_RECHERCHE": StateDef("CLIC_RECHERCHE", on_enter=on_enter_clic_recherche, on_tick=on_tick_clic_recherche),
    "END": StateDef("END", on_enter=on_enter_end),
}

ALL_STATES = {
    **COMMON_STATES,
    **PURCHASE_STATES,
    **SALE_STATES,
}


def run(resources: Sequence[dict], fortune_lines: Optional[Sequence[dict]] = None) -> None:
    """Run the marketplace FSM with the provided resources."""

    fortune_lines = list(fortune_lines or [])
    ctx = create_context(resources=resources, fortune_lines=fortune_lines, monitor_index=MONITOR_INDEX)

    fsm = FSM(states=ALL_STATES, start="LANCEMENT", end="END")
    fsm.ctx = ctx

    try:
        fsm.run(tick_hz=TICK_HZ)
    finally:
        try:
            for res in resources:
                template_path = res.get("template_path")
                if template_path and os.path.isfile(template_path):
                    os.remove(template_path)
        except Exception:
            pass


__all__ = ["run"]
