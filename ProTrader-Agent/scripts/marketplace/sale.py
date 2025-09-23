"""Sale-related FSM states for the marketplace workflow."""
from __future__ import annotations

import time
from typing import Dict, Optional, Tuple, TYPE_CHECKING

from utils.fsm import StateDef
from utils.logger import get_logger

from .config import (
    ONGLET_ACHAT_PATH,
    ONGLET_VENTE_PATH,
    SALE_QTY_ORDER,
    SEL_VENTE_PATHS,
    VENTE_CLICK_MAX_ATTEMPTS,
    VENTE_FALLBACK_OFFSET_PX,
    VENTE_FALLBACK_REGION_RATIO,
    VENTE_PATHS,
)
from .purchase import _parse_quantity_label
from .telemetry import _send_sale_event, _send_state

logger = get_logger(__name__)

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from typing import Callable

    from utils.keyboard import hotkey as HotkeyFn, press_key as PressKeyFn, type_text as TypeTextFn
    from utils.mouse import move_click as MoveClickFn
    from utils.vision import (
        find_template_on_screen as FindTemplateFn,
        find_template_on_screen_alpha as FindTemplateAlphaFn,
    )

_hotkey = None
_press_key = None
_type_text = None
_move_click_impl = None
_find_template_impl = None
_find_template_alpha_impl = None


def _ensure_keyboard():
    global _hotkey, _press_key, _type_text
    if _hotkey is None or _press_key is None or _type_text is None:
        from utils.keyboard import hotkey as hk, press_key as pk, type_text as tt

        _hotkey, _press_key, _type_text = hk, pk, tt
    return _hotkey, _press_key, _type_text


def _ensure_mouse():
    global _move_click_impl
    if _move_click_impl is None:
        from utils.mouse import move_click as mc

        _move_click_impl = mc
    return _move_click_impl


def _ensure_vision():
    global _find_template_impl, _find_template_alpha_impl
    if _find_template_impl is None or _find_template_alpha_impl is None:
        from utils.vision import find_template_on_screen, find_template_on_screen_alpha

        _find_template_impl = find_template_on_screen
        _find_template_alpha_impl = find_template_on_screen_alpha
    return _find_template_impl, _find_template_alpha_impl


def _fill_price(price_text: str) -> None:
    """Fill the price input and validate with the Enter key."""

    hotkey, press_key, type_text = _ensure_keyboard()

    hotkey(["ctrl", "a"])
    type_text(price_text)
    time.sleep(0.15)
    press_key("enter")


def on_enter_vente_onglet(fsm):
    _send_state("VENTE_ONGLET")


def on_tick_vente_onglet(fsm):
    sale = getattr(fsm.ctx, "current_sale", None)
    if not sale:
        logger.warning("VENTE_ONGLET sans vente en cours, retour à la recherche")
        return "CLIC_RECHERCHE"

    find_template_on_screen, _ = _ensure_vision()
    res = find_template_on_screen(
        template_path=str(ONGLET_VENTE_PATH),
        debug=True,
    )

    if res:
        time.sleep(1)
        move_click = _ensure_mouse()
        move_click(res.center[0], res.center[1])
        time.sleep(1)
        return "VENTE_SELECTION_RESSOURCE"


def on_enter_vente_selection_ressource(fsm):
    _send_state("VENTE_SELECTION_RESSOURCE")


def on_tick_vente_selection_ressource(fsm):
    sale = getattr(fsm.ctx, "current_sale", None)
    if not sale:
        logger.warning(
            "VENTE_SELECTION_RESSOURCE sans vente en cours, retour à la recherche"
        )
        return "CLIC_RECHERCHE"

    template_path = sale.get("template_path") or getattr(fsm.ctx, "template_path", "")
    if not template_path:
        logger.warning("Template ressource manquant pour la vente, on annule")
        fsm.ctx.current_sale = None
        return "CLIC_RECHERCHE"

    region = getattr(fsm.ctx, "right_half_region", None)
    _, find_template_on_screen_alpha = _ensure_vision()
    res = find_template_on_screen_alpha(
        template_path=template_path,
        scales=(0.58, 1.3, 1.1),
        threshold=0.67,
        use_color=True,
        region=region,
        debug=True,
    )

    if res:
        time.sleep(1)
        move_click = _ensure_mouse()
        move_click(res.center[0], res.center[1])
        time.sleep(0.5)
        return "VENTE_SELECTION_QTE"


def on_enter_vente_selection_qte(fsm):
    _send_state("VENTE_SELECTION_QTE")
    sale = getattr(fsm.ctx, "current_sale", None)
    if isinstance(sale, dict):
        sale["sel_attempts"] = 0
        sale["sel_use_alternatives"] = False
        sale.pop("selected_sel_qty", None)
        sale.pop("selected_sel_bbox", None)
        sale.pop("vente_fallback_click", None)
        sale.pop("saisie_force_tab", None)


def on_tick_vente_selection_qte(fsm):
    sale = getattr(fsm.ctx, "current_sale", None)
    if not sale:
        logger.warning("VENTE_SELECTION_QTE sans vente en cours, retour à la recherche")
        return "CLIC_RECHERCHE"

    use_alternatives = sale.get("sel_use_alternatives", False)
    qty = sale.get("qty")
    find_template_on_screen, _ = _ensure_vision()
    move_click = _ensure_mouse()

    candidate_qtys = []
    if not use_alternatives and qty in SEL_VENTE_PATHS:
        candidate_qtys = [qty]
    else:
        sale["sel_use_alternatives"] = True
        candidate_qtys = [q for q in SALE_QTY_ORDER if q in SEL_VENTE_PATHS]

    for candidate in candidate_qtys:
        path = SEL_VENTE_PATHS.get(candidate)
        if not path:
            continue
        res = find_template_on_screen(template_path=str(path), debug=True)
        if res:
            sale["selected_sel_qty"] = candidate
            sale["selected_sel_bbox"] = (
                int(res.left),
                int(res.top),
                int(res.width),
                int(res.height),
            )
            if candidate == qty:
                time.sleep(1)
                sale["selected_sale_qty"] = candidate
                sale.pop("vente_fallback_click", None)
                sale.pop("saisie_force_tab", None)
                sale["vente_attempts"] = 0
                return "VENTE_SAISIE"
            move_click(res.center[0], res.center[1])
            time.sleep(0.5)
            return "VENTE_CLIQUER_VENTE"

    if not use_alternatives:
        sale["sel_attempts"] = sale.get("sel_attempts", 0) + 1
        if sale["sel_attempts"] >= 3:
            sale["sel_use_alternatives"] = True


def on_enter_vente_cliquer_vente(fsm):
    _send_state("VENTE_CLIQUER_VENTE")
    sale = getattr(fsm.ctx, "current_sale", None)
    if isinstance(sale, dict):
        sale["vente_attempts"] = 0
        sale.pop("vente_fallback_click", None)
        sale.pop("saisie_force_tab", None)


def on_tick_vente_cliquer_vente(fsm):
    sale = getattr(fsm.ctx, "current_sale", None)
    if not sale:
        logger.warning("VENTE_CLIQUER_VENTE sans vente en cours, retour à la recherche")
        return "CLIC_RECHERCHE"

    preferred = sale.get("selected_sel_qty") or sale.get("qty")
    candidate_qtys = []
    if preferred in VENTE_PATHS:
        candidate_qtys.append(preferred)
    candidate_qtys.extend(
        [q for q in SALE_QTY_ORDER if q in VENTE_PATHS and q not in candidate_qtys]
    )

    region = getattr(fsm.ctx, "right_half_region", None)
    find_template_on_screen, _ = _ensure_vision()
    move_click = _ensure_mouse()

    for candidate in candidate_qtys:
        path = VENTE_PATHS.get(candidate)
        if not path:
            continue
        res = find_template_on_screen(
            template_path=str(path),
            debug=True,
            region=region,
        )
        if res:
            move_click(res.center[0], res.center[1])
            sale["selected_sale_qty"] = candidate
            sale["vente_attempts"] = 0
            sale.pop("vente_fallback_click", None)
            sale.pop("saisie_force_tab", None)
            time.sleep(0.5)
            return "VENTE_SAISIE"

    sale["vente_attempts"] = sale.get("vente_attempts", 0) + 1

    if sale["vente_attempts"] >= VENTE_CLICK_MAX_ATTEMPTS:
        sale["vente_attempts"] = 0
        sale["selected_sale_qty"] = sale.get("selected_sel_qty") or sale.get("qty")
        bbox = sale.get("selected_sel_bbox")
        fallback_click: Optional[Tuple[int, int]] = None
        if bbox:
            left, top, width, height = bbox
            fallback_y = int(top + height / 2)
            if region:
                ratio = max(0.05, min(0.95, VENTE_FALLBACK_REGION_RATIO))
                rel_x = int(region[2] * ratio)
                rel_x = max(5, min(rel_x, max(region[2] - 5, 5)))
                fallback_x = int(region[0] + rel_x)
            else:
                fallback_x = int(left + width + VENTE_FALLBACK_OFFSET_PX)
            fallback_click = (fallback_x, fallback_y)
        elif region:
            ratio = max(0.05, min(0.95, VENTE_FALLBACK_REGION_RATIO))
            rel_x = int(region[2] * ratio)
            rel_x = max(5, min(rel_x, max(region[2] - 5, 5)))
            fallback_x = int(region[0] + rel_x)
            fallback_y = int(region[1] + region[3] // 2)
            fallback_click = (fallback_x, fallback_y)

        if fallback_click:
            sale["vente_fallback_click"] = fallback_click
            logger.debug(
                "VENTE_CLIQUER_VENTE: fallback sur clic (%d, %d)",
                fallback_click[0],
                fallback_click[1],
            )
        else:
            sale["saisie_force_tab"] = True
            logger.debug(
                "VENTE_CLIQUER_VENTE: aucun fallback de clic, tab forcé pour la saisie",
            )

        logger.warning(
            "VENTE_CLIQUER_VENTE: template vente introuvable, passage en saisie directe"
        )
        return "VENTE_SAISIE"


def on_enter_vente_saisie(fsm):
    _send_state("VENTE_SAISIE")
    sale = getattr(fsm.ctx, "current_sale", None)
    if isinstance(sale, dict):
        sale["saisie_done"] = False


def on_tick_vente_saisie(fsm):
    sale = getattr(fsm.ctx, "current_sale", None)
    if not sale:
        logger.warning("VENTE_SAISIE sans vente en cours, retour à la recherche")
        return "CLIC_RECHERCHE"

    if sale.get("saisie_done"):
        return "VENTE_RETOUR_ACHAT"

    move_click = _ensure_mouse()
    _, press_key, _ = _ensure_keyboard()

    fallback_click = sale.pop("vente_fallback_click", None)
    if fallback_click:
        move_click(int(fallback_click[0]), int(fallback_click[1]))
        time.sleep(0.4)

    if sale.pop("saisie_force_tab", False):
        press_key("tab")
        time.sleep(0.2)

    time.sleep(1)

    price_value = None
    fortune_line: Dict[str, object] = sale.get("fortune_line") or {}
    median_value = fortune_line.get("median_price_7d")
    if median_value is not None:
        try:
            price_value = int(round(float(median_value)))
        except (TypeError, ValueError):
            price_value = None

    if price_value is None:
        fallback_price = sale.get("price")
        if fallback_price is not None:
            try:
                price_value = int(round(float(fallback_price)))
            except (TypeError, ValueError):
                price_value = None

    if price_value is None:
        logger.warning("Impossible de déterminer le prix de vente, valeur 0 utilisée")
        price_value = 0

    try:
        total_amount = int(price_value)
    except (TypeError, ValueError):
        total_amount = 0
    total_amount = max(0, total_amount)
    price_text = str(total_amount)

    _fill_price(price_text)

    quantity_label = (
        sale.get("selected_sale_qty")
        or sale.get("selected_sel_qty")
        or sale.get("qty")
        or ""
    )
    quantity_value = _parse_quantity_label(quantity_label)
    unit_price = float(total_amount)
    if quantity_value > 0:
        unit_price = float(total_amount) / float(quantity_value)

    _send_sale_event(
        resource=str(sale.get("slug", "")),
        quantity_label=str(quantity_label),
        quantity_value=quantity_value,
        unit_price=unit_price,
        total_amount=total_amount,
    )

    sale["saisie_done"] = True
    return "VENTE_RETOUR_ACHAT"


def on_enter_vente_retour_achat(fsm):
    _send_state("VENTE_RETOUR_ACHAT")


def on_tick_vente_retour_achat(fsm):
    sale = getattr(fsm.ctx, "current_sale", None)
    if not sale and not getattr(fsm.ctx, "completed_purchases", []):
        return "CLIC_RECHERCHE"

    find_template_on_screen, _ = _ensure_vision()
    res = find_template_on_screen(
        template_path=str(ONGLET_ACHAT_PATH),
        debug=True,
    )

    if res:
        time.sleep(1)
        move_click = _ensure_mouse()
        move_click(res.center[0], res.center[1])
        time.sleep(1)
        fsm.ctx.current_sale = None
        if getattr(fsm.ctx, "completed_purchases", []):
            fsm.ctx.current_sale = fsm.ctx.completed_purchases.pop(0)
            return "VENTE_ONGLET"
        fsm.ctx.skip_recherche_click = True
        return "CLIC_RECHERCHE"


SALE_STATES = {
    "VENTE_ONGLET": StateDef("VENTE_ONGLET", on_enter=on_enter_vente_onglet, on_tick=on_tick_vente_onglet),
    "VENTE_SELECTION_RESSOURCE": StateDef(
        "VENTE_SELECTION_RESSOURCE",
        on_enter=on_enter_vente_selection_ressource,
        on_tick=on_tick_vente_selection_ressource,
    ),
    "VENTE_SELECTION_QTE": StateDef(
        "VENTE_SELECTION_QTE",
        on_enter=on_enter_vente_selection_qte,
        on_tick=on_tick_vente_selection_qte,
    ),
    "VENTE_CLIQUER_VENTE": StateDef(
        "VENTE_CLIQUER_VENTE",
        on_enter=on_enter_vente_cliquer_vente,
        on_tick=on_tick_vente_cliquer_vente,
    ),
    "VENTE_SAISIE": StateDef(
        "VENTE_SAISIE", on_enter=on_enter_vente_saisie, on_tick=on_tick_vente_saisie
    ),
    "VENTE_RETOUR_ACHAT": StateDef(
        "VENTE_RETOUR_ACHAT",
        on_enter=on_enter_vente_retour_achat,
        on_tick=on_tick_vente_retour_achat,
    ),
}

__all__ = [
    "SALE_STATES",
]
