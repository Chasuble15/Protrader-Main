import os
import types
from pathlib import Path
import time

from settings import CONFIG_PATH
from utils.config_io import load_config_yaml, parse_yaml_to_dict
from utils.fsm import FSM, StateDef
from utils.misc import open_dofus, close_dofus
from utils.mouse import move_click
from utils.keyboard import type_text
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

def on_enter_scan_prix(fsm):
    _send_state("SCAN_PRIX")

    # Cibles à scanner (ordre libre)
    fsm.ctx.targets = [
        ("x1",   str(QTE_X1_PATH)),
        ("x10",  str(QTE_X10_PATH)),
        ("x100", str(QTE_X100_PATH)),
        ("x1000",str(QTE_X1000_PATH)),
    ]
    # None = pas encore scanné ; int = prix ; -1 = ignoré (introuvable)
    fsm.ctx.scanned = {k: None for k, _ in fsm.ctx.targets}
    # Compteur de tentatives par quantité
    fsm.ctx.attempts = {k: 0 for k, _ in fsm.ctx.targets}



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
        val = ocr_read_int(ocrzone, debug=True)

        if val is not None:
            _send_price(slug=slug, qty=qty, price=int(val))
            fsm.ctx.scanned[qty] = int(val)  # marquer comme scanné OK
        else:
            # OCR non concluant : on retentera à un prochain tick
            fsm.ctx.attempts[qty] += 1
            if fsm.ctx.attempts[qty] >= SCAN_MAX_ATTEMPTS_PER_QTY:
                fsm.ctx.scanned[qty] = -1  # ignoré après N essais

        # Traiter une seule qty par tick
        break

    # Si toutes les quantités sont traitées (prix lu ou ignorée), on termine
    if all(v is not None for v in fsm.ctx.scanned.values()):
        return "CLIC_RECHERCHE"

def on_enter_clic_recherche(fsm):
    _send_state("CLIC_RECHERCHE")

def on_tick_clic_recherche(fsm):
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
    "CLIC_RECHERCHE": StateDef("CLIC_RECHERCHE", on_enter=on_enter_clic_recherche, on_tick=on_tick_clic_recherche),
    "END": StateDef("END", on_enter=on_enter_end),
}


def run(resources):
    fsm = FSM(states=states, start="LANCEMENT", end="END")
    # expose la liste des ressources et l'indice courant
    fsm.ctx = types.SimpleNamespace(resources=resources, resource_index=0, slug="", template_path="")

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
