import os
import types
from pathlib import Path
import time
from datetime import datetime, timezone
from typing import Optional, Tuple

import mss

from settings import CONFIG_PATH
from utils.config_io import load_config_yaml, parse_yaml_to_dict
from utils.fsm import FSM, StateDef
from utils.misc import open_dofus, close_dofus
from utils.mouse import move_click
from utils.keyboard import type_text, press_key, hotkey
from utils.vision import find_template_on_screen, find_template_on_screen_alpha
from utils.ocr import ocr_read_int

from utils.logger import get_logger

logger = get_logger(__name__)

import bus

config = parse_yaml_to_dict(load_config_yaml(CONFIG_PATH))
BTN_JOUER_PATH = Path(config["base_dir"]) / config["templates"]["btn_jouer"]
EST_EN_JEU_PATH= Path(config["base_dir"]) / config["templates"]["est_en_jeu"]
OUVRIR_HDV_PATH = Path(config["base_dir"]) / config["templates"]["ouvrir_hdv"]
ATTENTE_HDV_PATH = Path(config["base_dir"]) / config["templates"]["attente_hdv"]
QTE_X1_PATH = Path(config["base_dir"]) / config["templates"]["qte_x1"]
QTE_X10_PATH = Path(config["base_dir"]) / config["templates"]["qte_x10"]
QTE_X100_PATH = Path(config["base_dir"]) / config["templates"]["qte_x100"]
QTE_X1000_PATH = Path(config["base_dir"]) / config["templates"]["qte_x1000"]
RECHERCHE_PATH = Path(config["base_dir"]) / config["templates"]["recherche"]
KAMAS_PATH = Path(config["base_dir"]) / config["templates"]["kamas"]
ONGLET_ACHAT_PATH = Path(config["base_dir"]) / config["templates"]["onglet_achat"]
ONGLET_VENTE_PATH = Path(config["base_dir"]) / config["templates"]["onglet_vente"]

SEL_VENTE_PATHS = {
    "x1": Path(config["base_dir"]) / config["templates"]["sel_vente_x1"],
    "x10": Path(config["base_dir"]) / config["templates"]["sel_vente_x10"],
    "x100": Path(config["base_dir"]) / config["templates"]["sel_vente_x100"],
    "x1000": Path(config["base_dir"]) / config["templates"]["sel_vente_x1000"],
}

VENTE_PATHS = {
    "x1": Path(config["base_dir"]) / config["templates"]["vente_x1"],
    "x10": Path(config["base_dir"]) / config["templates"]["vente_x10"],
    "x100": Path(config["base_dir"]) / config["templates"]["vente_x100"],
    "x1000": Path(config["base_dir"]) / config["templates"]["vente_x1000"],
}

SALE_QTY_ORDER = ["x1", "x10", "x100", "x1000"]


def _compute_right_half_region() -> Optional[Tuple[int, int, int, int]]:
    """Retourne la région correspondant à la moitié droite de l'écran actif."""
    monitor_index = int(config.get("settings", {}).get("monitor_index", 1) or 1)
    try:
        with mss.mss() as sct:
            monitors = sct.monitors
            if monitor_index < 1 or monitor_index >= len(monitors):
                monitor_index = 1
            mon = monitors[monitor_index]
            width = int(mon.get("width", 0))
            height = int(mon.get("height", 0))
    except Exception as exc:  # pragma: no cover - best effort logging only
        logger.debug("Impossible de déterminer la moitié droite de l'écran: %s", exc)
        return None

    if width <= 0 or height <= 0:
        return None

    half_width = width // 2
    return (half_width, 0, width - half_width, height)


def _fill_price(price_text: str) -> None:
    """Renseigne le champ de prix puis valide avec Entrée."""
    hotkey(["ctrl", "a"])
    type_text(price_text)
    time.sleep(0.15)
    press_key("enter")

_CONFIRMER_TEMPLATE = config.get("templates", {}).get("confirmer_achat")
if _CONFIRMER_TEMPLATE:
    CONFIRMER_ACHAT_PATH = Path(config["base_dir"]) / _CONFIRMER_TEMPLATE
    if not CONFIRMER_ACHAT_PATH.exists():
        logger.warning("Template confirmer_achat introuvable: %s", CONFIRMER_ACHAT_PATH)
        CONFIRMER_ACHAT_PATH = None
else:
    CONFIRMER_ACHAT_PATH = None

def _send_state(name: str) -> None:
    """Envoie l'état courant au serveur si le client est disponible."""
    if bus.client:
        bus.client.send({"type": "login_state", "state": name})
    else:
        print("ERREUR CLIENT")


def _send_price(slug: str, qty: str, price: int) -> None:
    """Envoie au serveur un prix lu par OCR."""
    frame = {
        "type": "hdv_price",
        "ts": int(time.time()),
        "data": {
            "slug": slug,
            "qty": qty,         # "x1" | "x10" | "x100" | "x1000"
            "price": int(price),
        }
    }
    if bus.client:
        bus.client.send(frame)
    else:
        print("[WARN] bus.client indisponible, payload:", frame)


def _send_kamas(amount: int) -> None:
    """Envoie le montant de kamas courant au serveur."""
    frame = {
        "type": "kamas_value",
        "ts": int(time.time()),
        "data": {
            "amount": int(amount),
        },
    }
    if bus.client:
        bus.client.send(frame)
    else:
        print("[WARN] bus.client indisponible, payload:", frame)


def _try_read_kamas_amount() -> Optional[int]:
    """Tente de lire la fortune en kamas à l'écran."""
    res = find_template_on_screen(
        template_path=str(KAMAS_PATH),
        debug=True,
    )

    if not res:
        return None

    ocrzone = (res.left - 250, res.top, 245, res.height)
    ocrzone = tuple(int(v) for v in ocrzone)
    val = ocr_read_int(ocrzone, debug=True)

    if val is None:
        return None

    try:
        return int(val)
    except (TypeError, ValueError):
        logger.warning("Valeur de kamas invalide détectée: %s", val)
        return None


def _parse_quantity_label(qty: str) -> int:
    """Convertit un libellé de quantité (x1, x10, …) en entier."""
    if not qty:
        return 0
    qty = str(qty).strip().lower()
    if qty.startswith("x"):
        qty = qty[1:]
    try:
        return int(qty)
    except (TypeError, ValueError):
        return 0


def _current_iso_datetime() -> str:
    """Retourne l'heure courante en ISO8601 (UTC)."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _send_purchase_event(
    resource: str,
    quantity_label: str,
    quantity_value: int,
    unit_price: float,
    total_amount: int,
) -> None:
    """Envoie au serveur le détail d'un achat validé."""
    frame = {
        "type": "purchase_event",
        "ts": int(time.time()),
        "data": {
            "resource": resource,
            "quantity_label": quantity_label,
            "quantity": quantity_value,
            "price": float(unit_price),
            "amount": int(total_amount),
            "date": _current_iso_datetime(),
        },
    }
    if bus.client:
        bus.client.send(frame)
    else:
        print("[WARN] bus.client indisponible, payload:", frame)


def _build_fortune_lookup(fortune_lines):
    lookup = {}
    for line in fortune_lines or []:
        slug = (line.get("slug") or "").strip().lower()
        qty = (line.get("qty") or "").strip()
        if slug and qty:
            lookup.setdefault(slug, {})[qty] = line
    return lookup


def _get_fortune_line(fsm, slug: str, qty: str):
    slug_key = (slug or "").strip().lower()
    if not slug_key:
        return None
    lookup = getattr(getattr(fsm, "ctx", None), "fortune_lookup", {}) or {}
    return lookup.get(slug_key, {}).get(qty)


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


def on_enter_lancement(fsm):
    _send_state("LANCEMENT")
    open_dofus()


def on_tick_lancement(fsm):
    res = find_template_on_screen(
        template_path=str(BTN_JOUER_PATH),
        debug=True,
    )

    if res:
        time.sleep(1)
        move_click(res.center[0], res.center[1])
        return "ATTENTE_CONNEXION"


def on_enter_attente_connexion(fsm):
    _send_state("ATTENTE_CONNEXION")


def on_tick_attente_connexion(fsm):
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
    res = find_template_on_screen(
        template_path=str(OUVRIR_HDV_PATH),
        debug=True,
    )

    if res:
        time.sleep(1)
        move_click(res.center[0], res.center[1])
        return "ATTENTE_HDV"


def on_enter_attente_hdv(fsm):
    _send_state("ATTENTE_HDV")


def on_tick_attente_hdv(fsm):
    res = find_template_on_screen(
        template_path=str(ATTENTE_HDV_PATH),
        debug=True,
    )

    if res:
        time.sleep(1)
        return "GET_KAMAS"




def on_enter_entrer_ressource(fsm):
    _send_state("ENTRER_RESSOURCE")
    # sélectionne la ressource courante selon l'indice
    current = fsm.ctx.resources[fsm.ctx.resource_index]
    fsm.ctx.slug = current.get("slug", "")
    fsm.ctx.template_path = current.get("template_path", "")
    fsm.ctx.reset_scan = True
    fsm.ctx.pending_purchase = None
    fsm.ctx.completed_purchases = []
    fsm.ctx.current_sale = None
    fsm.ctx.skip_recherche_click = False
    type_text(fsm.ctx.slug or " ")
    return "SELECTION_RESSOURCE"


def on_enter_selection_ressource(fsm):
    _send_state("SELECTION_RESSOURCE")


def on_tick_selection_ressource(fsm):
    template_path = getattr(getattr(fsm, "ctx", None), "template_path", "") or ""
    if not template_path:
        _send_state("ERREUR_TEMPLATE_MANQUANT")
        return "END"

    res = find_template_on_screen_alpha(
        template_path=template_path,
        scales=(0.58, 1.3, 1.1),
        threshold=0.67,
        debug=True,
        use_color=True
    )
    if res:
        print(res)
        time.sleep(1)
        move_click(res.center[0], res.center[1])
        return "SCAN_PRIX"

# Nombre max de tentatives par quantité (à 2 Hz => 10 s)
SCAN_MAX_ATTEMPTS_PER_QTY = 5

CLIC_ACHAT_OFFSET_PX = 100
VENTE_CLICK_MAX_ATTEMPTS = 6
VENTE_FALLBACK_REGION_RATIO = 0.28
VENTE_FALLBACK_OFFSET_PX = 240
PURCHASE_MAX_RETRIES = 5
KAMAS_CHECK_MAX_ATTEMPTS = 10

def on_enter_scan_prix(fsm):
    _send_state("SCAN_PRIX")

    reset_scan = getattr(fsm.ctx, "reset_scan", True)

    if reset_scan or not getattr(fsm.ctx, "targets", None):
        # Cibles à scanner (ordre libre)
        fsm.ctx.targets = [
            ("x1",   str(QTE_X1_PATH)),
            ("x10",  str(QTE_X10_PATH)),
            ("x100", str(QTE_X100_PATH)),
            ("x1000",str(QTE_X1000_PATH)),
        ]
    if reset_scan or not getattr(fsm.ctx, "scanned", None):
        # None = pas encore scanné ; int = prix ; -1 = ignoré (introuvable)
        fsm.ctx.scanned = {k: None for k, _ in fsm.ctx.targets}
    if reset_scan or not getattr(fsm.ctx, "attempts", None):
        # Compteur de tentatives par quantité
        fsm.ctx.attempts = {k: 0 for k, _ in fsm.ctx.targets}

    fsm.ctx.reset_scan = False
    fsm.ctx.pending_purchase = None



def on_tick_scan_prix(fsm):
    slug = getattr(getattr(fsm, "ctx", None), "slug", "") or ""

    # Parcourt les quantités non encore traitées
    for qty, tpl in fsm.ctx.targets:
        if fsm.ctx.scanned.get(qty) is not None:  # déjà fait (prix ou ignoré)
            continue

        # Recherche du gabarit de quantité (x1, x10, ...)
        res = find_template_on_screen(template_path=tpl, debug=True)

        if not res:
            # Pas trouvé cette quantité à ce tick -> on compte et on peut ignorer si on dépasse
            fsm.ctx.attempts[qty] += 1
            if fsm.ctx.attempts[qty] >= SCAN_MAX_ATTEMPTS_PER_QTY:
                # Ignorer définitivement cette quantité
                fsm.ctx.scanned[qty] = -1  # -1 = skipped
                # (Optionnel) notifier le serveur que cette qty a été ignorée
                # if bus.client:
                #     bus.client.send({"type": "hdv_price_skipped", "ts": int(time.time()), "data": {"slug": slug, "qty": qty}})
            # On ne traite qu'une seule qty par tick pour la stabilité
            break

        # Si trouvé, lire le prix via OCR
        ocrzone = (res.left + 150, res.top, 245, res.height)
        ocrzone = tuple(int(v) for v in ocrzone)
        val = ocr_read_int(ocrzone, debug=True)

        if val is not None:
            price_val = int(val)
            _send_price(slug=slug, qty=qty, price=price_val)
            fortune_line = _get_fortune_line(fsm, slug, qty)
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
            fsm.ctx.scanned[qty] = price_val  # marquer comme scanné OK
        else:
            # OCR non concluant : on retentera à un prochain tick
            fsm.ctx.attempts[qty] += 1
            if fsm.ctx.attempts[qty] >= SCAN_MAX_ATTEMPTS_PER_QTY:
                fsm.ctx.scanned[qty] = -1  # ignoré après N essais

        # Traiter une seule qty par tick
        break

    # Si toutes les quantités sont traitées (prix lu ou ignorée), on termine
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


def on_enter_vente_onglet(fsm):
    _send_state("VENTE_ONGLET")


def on_tick_vente_onglet(fsm):
    sale = getattr(fsm.ctx, "current_sale", None)
    if not sale:
        logger.warning("VENTE_ONGLET sans vente en cours, retour à la recherche")
        return "CLIC_RECHERCHE"

    res = find_template_on_screen(
        template_path=str(ONGLET_VENTE_PATH),
        debug=True,
    )

    if res:
        time.sleep(1)
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
            else:
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
        fallback_click = None
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

    fallback_click = sale.pop("vente_fallback_click", None)
    if fallback_click:
        move_click(int(fallback_click[0]), int(fallback_click[1]))
        time.sleep(0.4)

    if sale.pop("saisie_force_tab", False):
        press_key("tab")
        time.sleep(0.2)

    time.sleep(1)

    price_value = None
    fortune_line = sale.get("fortune_line") or {}
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

    price_text = str(max(0, price_value))

    # Renseigne le prix puis valide la saisie
    _fill_price(price_text)

    sale["saisie_done"] = True
    return "VENTE_RETOUR_ACHAT"


def on_enter_vente_retour_achat(fsm):
    _send_state("VENTE_RETOUR_ACHAT")


def on_tick_vente_retour_achat(fsm):
    sale = getattr(fsm.ctx, "current_sale", None)
    if not sale and not getattr(fsm.ctx, "completed_purchases", []):
        return "CLIC_RECHERCHE"

    res = find_template_on_screen(
        template_path=str(ONGLET_ACHAT_PATH),
        debug=True,
    )

    if res:
        time.sleep(1)
        move_click(res.center[0], res.center[1])
        time.sleep(1)
        fsm.ctx.current_sale = None
        if getattr(fsm.ctx, "completed_purchases", []):
            fsm.ctx.current_sale = fsm.ctx.completed_purchases.pop(0)
            return "VENTE_ONGLET"
        fsm.ctx.skip_recherche_click = True
        return "CLIC_RECHERCHE"


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

    res = find_template_on_screen(
        template_path=str(RECHERCHE_PATH),
        debug=True,
    )

    if res:
        time.sleep(1)
        move_click(res.center[0], res.center[1])
        time.sleep(1)
        # Passe à la ressource suivante si disponible
        fsm.ctx.resource_index += 1
        if fsm.ctx.resource_index < len(fsm.ctx.resources):
            return "ENTRER_RESSOURCE"
        return "END"

def on_enter_end(fsm):
    _send_state("END")
    close_dofus()
    # Extinction de l'ordinateur lorsque le script est terminé
    if os.name == "nt":
        os.system("shutdown /s /t 0")
    else:
        os.system("shutdown -h now")


def on_enter_get_kamas(fsm):
    _send_state("GET_KAMAS")

def on_tick_get_kamas(fsm):
    # Rechercher le symbole de kamas dans l'interface
    kamas_value = _try_read_kamas_amount()

    if kamas_value is not None:
        fsm.ctx.current_kamas = kamas_value
        logger.info("Fortune actuelle : %d K", kamas_value)
        _send_kamas(kamas_value)
        return "ENTRER_RESSOURCE"



states = {
    "LANCEMENT": StateDef("LANCEMENT", on_enter=on_enter_lancement, on_tick=on_tick_lancement),
    "ATTENTE_CONNEXION": StateDef(
        "ATTENTE_CONNEXION", on_enter=on_enter_attente_connexion, on_tick=on_tick_attente_connexion
    ),
    "EN_JEU": StateDef("EN_JEU", on_enter=on_enter_en_jeu),
    "OUVRIR_HDV": StateDef("OUVRIR_HDV", on_enter=on_enter_ouvrir_hdv, on_tick=on_tick_ouvrir_hdv),
    "ATTENTE_HDV": StateDef("ATTENTE_HDV", on_enter=on_enter_attente_hdv, on_tick=on_tick_attente_hdv),
    "GET_KAMAS": StateDef("GET_KAMAS", on_enter=on_enter_get_kamas, on_tick=on_tick_get_kamas),
    "ENTRER_RESSOURCE": StateDef("ENTRER_RESSOURCE", on_enter=on_enter_entrer_ressource),
    "SELECTION_RESSOURCE": StateDef("SELECTION_RESSOURCE", on_enter=on_enter_selection_ressource, on_tick=on_tick_selection_ressource),
    "SCAN_PRIX": StateDef("SCAN_PRIX", on_enter=on_enter_scan_prix, on_tick=on_tick_scan_prix),
    "CLIC_ACHAT": StateDef("CLIC_ACHAT", on_enter=on_enter_clic_achat, on_tick=on_tick_clic_achat),
    "VERIFIER_ACHAT": StateDef(
        "VERIFIER_ACHAT",
        on_enter=on_enter_verifier_achat,
        on_tick=on_tick_verifier_achat,
    ),
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
    "VENTE_SAISIE": StateDef("VENTE_SAISIE", on_enter=on_enter_vente_saisie, on_tick=on_tick_vente_saisie),
    "VENTE_RETOUR_ACHAT": StateDef(
        "VENTE_RETOUR_ACHAT",
        on_enter=on_enter_vente_retour_achat,
        on_tick=on_tick_vente_retour_achat,
    ),
    "CLIC_RECHERCHE": StateDef("CLIC_RECHERCHE", on_enter=on_enter_clic_recherche, on_tick=on_tick_clic_recherche),
    "END": StateDef("END", on_enter=on_enter_end),
}


def run(resources, fortune_lines=None):
    fortune_lines = fortune_lines or []
    fsm = FSM(states=states, start="LANCEMENT", end="END")
    # expose la liste des ressources et l'indice courant
    fsm.ctx = types.SimpleNamespace(
        resources=resources,
        resource_index=0,
        slug="",
        template_path="",
        fortune_lines=fortune_lines,
        fortune_lookup=_build_fortune_lookup(fortune_lines),
        pending_purchase=None,
        reset_scan=True,
        completed_purchases=[],
        current_sale=None,
        current_kamas=None,
        right_half_region=_compute_right_half_region(),
        skip_recherche_click=False,
    )

    try:
        fsm.run(tick_hz=2)
    finally:
        # nettoyage des PNG temporaires
        try:
            for r in resources:
                tp = r.get("template_path")
                if tp and os.path.isfile(tp):
                    os.remove(tp)
        except Exception:
            pass
