"""Purchase-related FSM states for the marketplace workflow."""
from __future__ import annotations

import time
from typing import Optional, TYPE_CHECKING

from utils.fsm import StateDef
from utils.logger import get_logger

from .config import (
    CLIC_ACHAT_OFFSET_PX,
    CONFIRMER_ACHAT_PATH,
    KAMAS_CHECK_MAX_ATTEMPTS,
    KAMAS_PATH,
    PURCHASE_MAX_RETRIES,
    QTE_X1000_PATH,
    QTE_X100_PATH,
    QTE_X10_PATH,
    QTE_X1_PATH,
    SCAN_MAX_ATTEMPTS_PER_QTY,
)
from .context import get_fortune_line
from .telemetry import (
    _send_kamas,
    _send_price,
    _send_purchase_event,
    _send_state,
)

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from typing import Callable, Tuple

    from utils.keyboard import hotkey as HotkeyFn, press_key as PressKeyFn, type_text as TypeTextFn
    from utils.mouse import move_click as MoveClickFn
    from utils.ocr import ocr_read_int as OcrReadIntFn
    from utils.vision import (
        find_template_on_screen as FindTemplateFn,
        find_template_on_screen_alpha as FindTemplateAlphaFn,
    )

logger = get_logger(__name__)

_hotkey = None
_press_key = None
_type_text = None
_move_click_impl = None
_find_template_impl = None
_find_template_alpha_impl = None
_ocr_reader = None


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


def _ensure_ocr():
    global _ocr_reader
    if _ocr_reader is None:
        from utils.ocr import ocr_read_int as reader

        _ocr_reader = reader
    return _ocr_reader


def _try_read_kamas_amount() -> Optional[int]:
    """Attempt to read the kamas fortune from the screen."""

    find_template_on_screen, _ = _ensure_vision()
    res = find_template_on_screen(
        template_path=str(KAMAS_PATH),
        debug=True,
    )

    if not res:
        return None

    ocrzone = (res.left - 250, res.top, 245, res.height)
    ocrzone = tuple(int(v) for v in ocrzone)
    ocr_read_int = _ensure_ocr()
    val = ocr_read_int(ocrzone, debug=True)

    if val is None:
        return None

    try:
        return int(val)
    except (TypeError, ValueError):
        logger.warning("Valeur de kamas invalide détectée: %s", val)
        return None


def _parse_quantity_label(qty: str) -> int:
    """Convert quantity labels such as 'x10' into integers."""

    if not qty:
        return 0
    qty = str(qty).strip().lower()
    if qty.startswith("x"):
        qty = qty[1:]
    try:
        return int(qty)
    except (TypeError, ValueError):
        return 0


def _compute_purchase_threshold(fortune_line):
    """Return the maximum price allowed for a purchase based on fortune settings."""

    if not isinstance(fortune_line, dict):
        return None

    margin_type = str(fortune_line.get("margin_type") or "").strip().lower()
    margin_value = fortune_line.get("margin_value")
    try:
        margin_value = float(margin_value)
    except (TypeError, ValueError):
        return None

    if margin_type == "percent":
        median_value = fortune_line.get("median_price_7d")
        try:
            median_value = float(median_value)
        except (TypeError, ValueError):
            return None
        threshold = median_value - (median_value * margin_value / 100.0)
    elif margin_type == "absolute":
        threshold = margin_value
    else:
        return None

    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        return None

    if threshold < 0:
        threshold = 0

    return int(threshold)


def on_enter_entrer_ressource(fsm):
    _send_state("ENTRER_RESSOURCE")
    current = fsm.ctx.resources[fsm.ctx.resource_index]
    fsm.ctx.slug = current.get("slug", "")
    fsm.ctx.template_path = current.get("template_path", "")
    fsm.ctx.reset_scan = True
    fsm.ctx.pending_purchase = None
    fsm.ctx.completed_purchases = []
    fsm.ctx.current_sale = None
    fsm.ctx.skip_recherche_click = False
    _, _, type_text = _ensure_keyboard()
    type_text(fsm.ctx.slug or " ")
    return "SELECTION_RESSOURCE"


def on_enter_selection_ressource(fsm):
    _send_state("SELECTION_RESSOURCE")


def on_tick_selection_ressource(fsm):
    template_path = getattr(getattr(fsm, "ctx", None), "template_path", "") or ""
    if not template_path:
        _send_state("ERREUR_TEMPLATE_MANQUANT")
        return "END"

    _, find_template_on_screen_alpha = _ensure_vision()
    res = find_template_on_screen_alpha(
        template_path=template_path,
        scales=(0.58, 1.3, 1.1),
        threshold=0.67,
        debug=True,
        use_color=True,
    )
    if res:
        time.sleep(1)
        move_click = _ensure_mouse()
        move_click(res.center[0], res.center[1])
        return "SCAN_PRIX"


def on_enter_scan_prix(fsm):
    _send_state("SCAN_PRIX")

    reset_scan = getattr(fsm.ctx, "reset_scan", True)

    if reset_scan or not getattr(fsm.ctx, "targets", None):
        fsm.ctx.targets = [
            ("x1", str(QTE_X1_PATH)),
            ("x10", str(QTE_X10_PATH)),
            ("x100", str(QTE_X100_PATH)),
            ("x1000", str(QTE_X1000_PATH)),
        ]
    if reset_scan or not getattr(fsm.ctx, "scanned", None):
        fsm.ctx.scanned = {k: None for k, _ in fsm.ctx.targets}
    if reset_scan or not getattr(fsm.ctx, "attempts", None):
        fsm.ctx.attempts = {k: 0 for k, _ in fsm.ctx.targets}

    fsm.ctx.reset_scan = False
    fsm.ctx.pending_purchase = None


def on_tick_scan_prix(fsm):
    slug = getattr(getattr(fsm, "ctx", None), "slug", "") or ""
    find_template_on_screen, _ = _ensure_vision()
    ocr_read_int = _ensure_ocr()

    for qty, tpl in fsm.ctx.targets:
        if fsm.ctx.scanned.get(qty) is not None:
            continue

        res = find_template_on_screen(template_path=tpl, debug=True)

        if not res:
            fsm.ctx.attempts[qty] += 1
            if fsm.ctx.attempts[qty] >= SCAN_MAX_ATTEMPTS_PER_QTY:
                fsm.ctx.scanned[qty] = -1
            break

        ocrzone = (res.left + 150, res.top, 245, res.height)
        ocrzone = tuple(int(v) for v in ocrzone)
        val = ocr_read_int(ocrzone, debug=True)

        if val is not None:
            try:
                price_val = int(val)
            except (TypeError, ValueError):
                price_val = None
            if price_val is not None:
                _send_price(slug=slug, qty=qty, price=price_val)
                fortune_line = get_fortune_line(fsm.ctx, slug, qty)
                should_purchase = False
                target_price = None
                if fortune_line:
                    target_price = _compute_purchase_threshold(fortune_line)
                    if target_price is None:
                        logger.info(
                            "Seuil d'achat introuvable pour %s (%s), marge=%s",
                            slug,
                            qty,
                            fortune_line.get("margin_type"),
                        )
                    elif price_val > target_price:
                        logger.debug(
                            "Prix %d supérieur au seuil %d pour %s (%s), achat ignoré",
                            price_val,
                            target_price,
                            slug,
                            qty,
                        )
                    else:
                        current_kamas = getattr(getattr(fsm, "ctx", None), "current_kamas", None)
                        kamas_value = None
                        if current_kamas is not None:
                            try:
                                kamas_value = int(current_kamas)
                            except (TypeError, ValueError):
                                kamas_value = None
                        if kamas_value is None:
                            logger.info(
                                "Fortune en kamas inconnue, achat ignoré pour %s (%s)",
                                slug,
                                qty,
                            )
                        else:
                            max_allowed_price = max(0, int(kamas_value * 0.10))
                            if price_val > max_allowed_price:
                                logger.info(
                                    "Prix %d supérieur à 10%% de la fortune (%d) pour %s (%s), achat ignoré",
                                    price_val,
                                    max_allowed_price,
                                    slug,
                                    qty,
                                )
                            else:
                                should_purchase = True
                if should_purchase:
                    fsm.ctx.pending_purchase = {
                        "slug": slug,
                        "qty": qty,
                        "price": price_val,
                        "ocrzone": ocrzone,
                        "fortune_line": fortune_line,
                        "click_done": False,
                        "retry_count": 0,
                    }
                    logger.info(
                        "Fortune active pour %s (%s), déclenchement de l'achat (prix=%d, seuil=%s)",
                        slug,
                        qty,
                        price_val,
                        target_price,
                    )
                    return "CLIC_ACHAT"
                fsm.ctx.scanned[qty] = price_val
            else:
                fsm.ctx.attempts[qty] += 1
                if fsm.ctx.attempts[qty] >= SCAN_MAX_ATTEMPTS_PER_QTY:
                    fsm.ctx.scanned[qty] = -1
        else:
            fsm.ctx.attempts[qty] += 1
            if fsm.ctx.attempts[qty] >= SCAN_MAX_ATTEMPTS_PER_QTY:
                fsm.ctx.scanned[qty] = -1
        break

    if all(v is not None for v in fsm.ctx.scanned.values()):
        if getattr(fsm.ctx, "current_sale", None) is None and getattr(
            fsm.ctx, "completed_purchases", []
        ):
            fsm.ctx.current_sale = fsm.ctx.completed_purchases.pop(0)
            return "VENTE_ONGLET"
        if getattr(fsm.ctx, "current_sale", None) is not None:
            return "VENTE_ONGLET"
        return "CLIC_RECHERCHE"


def on_enter_clic_achat(fsm):
    _send_state("CLIC_ACHAT")


def on_tick_clic_achat(fsm):
    pending = getattr(fsm.ctx, "pending_purchase", None)
    if not pending:
        logger.warning("CLIC_ACHAT sans achat en attente, retour au scan")
        return "SCAN_PRIX"

    move_click = _ensure_mouse()

    if not pending.get("click_done"):
        left, top, width, height = pending.get("ocrzone", (0, 0, 0, 0))
        click_x = int(left + width + CLIC_ACHAT_OFFSET_PX)
        click_y = int(top + height / 2)
        logger.debug("CLIC_ACHAT: clic sur Acheter en (%d, %d)", click_x, click_y)
        pending["attempt_start_kamas"] = getattr(fsm.ctx, "current_kamas", None)
        move_click(click_x, click_y)
        pending["click_done"] = True
        time.sleep(1)
        return

    if not CONFIRMER_ACHAT_PATH:
        logger.warning("Template confirmer_achat indisponible, validation ignorée")
        fsm.ctx.scanned[pending["qty"]] = pending["price"]
        fsm.ctx.pending_purchase = None
        return "SCAN_PRIX"

    find_template_on_screen, _ = _ensure_vision()
    res = find_template_on_screen(
        template_path=str(CONFIRMER_ACHAT_PATH),
        debug=True,
    )

    if res:
        logger.debug(
            "CLIC_ACHAT: confirmation trouvée, clic en (%d, %d)",
            res.center[0],
            res.center[1],
        )
        move_click(res.center[0], res.center[1])
        time.sleep(1)
        pending["kamas_check_attempts"] = 0
        return "VERIFIER_ACHAT"


def on_enter_verifier_achat(fsm):
    _send_state("VERIFIER_ACHAT")


def on_tick_verifier_achat(fsm):
    pending = getattr(fsm.ctx, "pending_purchase", None)
    if not pending:
        logger.warning("VERIFIER_ACHAT sans achat en attente, retour au scan")
        return "SCAN_PRIX"

    kamas_value = _try_read_kamas_amount()
    if kamas_value is None:
        attempts = int(pending.get("kamas_check_attempts", 0)) + 1
        pending["kamas_check_attempts"] = attempts
        if attempts >= KAMAS_CHECK_MAX_ATTEMPTS:
            logger.warning(
                "Impossible de lire la fortune après achat pour %s (%s) (tentative %d)",
                pending.get("slug"),
                pending.get("qty"),
                attempts,
            )
            pending["kamas_check_attempts"] = 0
        return

    previous_kamas = pending.get("attempt_start_kamas")
    if previous_kamas is None:
        previous_kamas = getattr(fsm.ctx, "current_kamas", None)
    try:
        previous_kamas = int(previous_kamas) if previous_kamas is not None else None
    except (TypeError, ValueError):
        previous_kamas = None

    if previous_kamas is not None and kamas_value == previous_kamas:
        pending["retry_count"] = int(pending.get("retry_count", 0)) + 1
        logger.info(
            "Achat non confirmé (fortune inchangée) pour %s (%s), tentative %d",
            pending.get("slug"),
            pending.get("qty"),
            pending["retry_count"],
        )
        if pending["retry_count"] >= PURCHASE_MAX_RETRIES:
            logger.warning(
                "Abandon de l'achat après %d tentatives pour %s (%s)",
                pending["retry_count"],
                pending.get("slug"),
                pending.get("qty"),
            )
            fsm.ctx.scanned[pending["qty"]] = pending.get("price")
            fsm.ctx.pending_purchase = None
            return "SCAN_PRIX"
        pending["click_done"] = False
        pending["kamas_check_attempts"] = 0
        time.sleep(1)
        return "CLIC_ACHAT"

    slug = pending.get("slug", "")
    qty_label = pending.get("qty", "")
    price_paid = pending.get("price")
    try:
        total_amount = int(price_paid)
    except (TypeError, ValueError):
        total_amount = 0

    quantity_value = _parse_quantity_label(qty_label)
    unit_price = float(total_amount)
    if quantity_value > 0:
        unit_price = float(total_amount) / float(quantity_value)

    logger.info(
        "Achat confirmé pour %s (%s) : %d kamas (fortune %s → %d)",
        slug,
        qty_label,
        total_amount,
        previous_kamas if previous_kamas is not None else "?",
        kamas_value,
    )

    fsm.ctx.current_kamas = kamas_value
    _send_kamas(kamas_value)
    _send_purchase_event(
        resource=slug,
        quantity_label=qty_label,
        quantity_value=quantity_value,
        unit_price=unit_price,
        total_amount=total_amount,
    )

    sale_queue = getattr(fsm.ctx, "completed_purchases", None)
    if isinstance(sale_queue, list):
        sale_queue.append(
            {
                "slug": slug,
                "qty": qty_label,
                "price": total_amount,
                "fortune_line": pending.get("fortune_line", {}),
                "template_path": getattr(fsm.ctx, "template_path", ""),
            }
        )

    fsm.ctx.scanned[pending["qty"]] = pending.get("price")
    fsm.ctx.pending_purchase = None
    return "SCAN_PRIX"


PURCHASE_STATES = {
    "ENTRER_RESSOURCE": StateDef("ENTRER_RESSOURCE", on_enter=on_enter_entrer_ressource),
    "SELECTION_RESSOURCE": StateDef(
        "SELECTION_RESSOURCE",
        on_enter=on_enter_selection_ressource,
        on_tick=on_tick_selection_ressource,
    ),
    "SCAN_PRIX": StateDef("SCAN_PRIX", on_enter=on_enter_scan_prix, on_tick=on_tick_scan_prix),
    "CLIC_ACHAT": StateDef("CLIC_ACHAT", on_enter=on_enter_clic_achat, on_tick=on_tick_clic_achat),
    "VERIFIER_ACHAT": StateDef(
        "VERIFIER_ACHAT",
        on_enter=on_enter_verifier_achat,
        on_tick=on_tick_verifier_achat,
    ),
}

__all__ = [
    "PURCHASE_STATES",
    "_compute_purchase_threshold",
    "_parse_quantity_label",
    "_try_read_kamas_amount",
]
