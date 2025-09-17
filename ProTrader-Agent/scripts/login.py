import os
import types
from pathlib import Path
import time
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


def _qty_to_int_string(qty: str) -> str:
    """Convertit une chaîne de type 'x100' en valeur numérique ('100')."""
    if not qty:
        return ""
    cleaned = qty.strip().lower()
    if cleaned.startswith("x"):
        cleaned = cleaned[1:]
    try:
        return str(int(float(cleaned)))
    except (TypeError, ValueError):
        return ""

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
            if fortune_line:
                fsm.ctx.pending_purchase = {
                    "slug": slug,
                    "qty": qty,
                    "price": price_val,
                    "ocrzone": ocrzone,
                    "fortune_line": fortune_line,
                    "click_done": False,
                }
                logger.info(
                    "Fortune active pour %s (%s), déclenchement de l'achat",
                    slug,
                    qty,
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
        sale_queue = getattr(fsm.ctx, "completed_purchases", None)
        if isinstance(sale_queue, list):
            sale_queue.append(
                {
                    "slug": pending.get("slug"),
                    "qty": pending.get("qty"),
                    "price": pending.get("price"),
                    "fortune_line": pending.get("fortune_line", {}),
                    "template_path": getattr(fsm.ctx, "template_path", ""),
                }
            )
        fsm.ctx.scanned[pending["qty"]] = pending["price"]
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
            if candidate == qty:
                time.sleep(1)
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

    for candidate in candidate_qtys:
        path = VENTE_PATHS.get(candidate)
        if not path:
            continue
        res = find_template_on_screen(template_path=str(path), debug=True)
        if res:
            move_click(res.center[0], res.center[1])
            sale["selected_sale_qty"] = candidate
            time.sleep(0.5)
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
    qty_text = _qty_to_int_string(sale.get("qty")) or "1"

    # Renseigne d'abord le prix médian, puis la quantité reçue
    hotkey(["ctrl", "a"])
    type_text(price_text)
    press_key("tab")
    hotkey(["ctrl", "a"])
    type_text(qty_text)
    press_key("enter")

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
    res = find_template_on_screen(
        template_path=str(KAMAS_PATH),
        debug=True,
    )

    if res:
        # Si trouvé, lire le montant de kamas via OCR
        ocrzone = (res.left - 250, res.top, 245, res.height)
        val = ocr_read_int(ocrzone, debug=True)

        if val is not None:
            logger.info("Fortune actuelle : %d K", val)
            _send_kamas(val)
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
