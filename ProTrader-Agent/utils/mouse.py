# mouse.py
# Prérequis:
#   pip install interception-python pyclick
#   -> Installer le driver Interception (redémarrage requis)
#   -> Exécuter en Administrateur

from __future__ import annotations
import ctypes
import platform
import time
import random
from typing import Literal, Tuple, Optional

import interception
from interception import beziercurve

__all__ = [
    "sleep",
    "point_near",
    "move",
    "click",
    "move_click",
    "drag",
    "set_bezier_speed",
    "set_seed",
]

# =========================
#  Initialisation globale
# =========================
# Capture auto du bon périphérique souris (via HID)
interception.auto_capture_devices(mouse=True)

# Paramètres de trajectoire "humaine" (Bézier) — ajustables
_default_params = beziercurve.BezierCurveParams()
beziercurve.set_default_params(_default_params)

# --- AJOUTS EN HAUT DU FICHIER (après les imports) ---
_is_windows = (platform.system() == "Windows")
if _is_windows:
    # Évite les décalages avec l’échelle DPI (125%, 150%, etc.)
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

def _set_cursor_pos(x: int, y: int) -> None:
    """
    Place le curseur **en pixels** sur le bureau virtuel Windows.
    Gère correctement multi-moniteurs et DPI.
    """
    if not _is_windows:
        # Fallback si tu portes le code ailleurs un jour
        interception.move_to(x, y)
        return
    ctypes.windll.user32.SetCursorPos(int(x), int(y))

def _get_cursor_pos() -> Tuple[int, int]:
    """Utile pour debug si besoin."""
    if not _is_windows:
        return (0, 0)
    pt = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y

# =========================
#  Helpers setup
# =========================
def set_bezier_speed(speed: float = 1.0, overshoot: float = 1.0, noise: float = 1.0) -> None:
    """
    Ajuste rapidement la "vitesse" perçue et le caractère humain du mouvement.
    - speed: >1.0 = plus rapide, <1.0 = plus lent
    - overshoot: >1.0 = plus d'overshoot
    - noise: >1.0 = plus de micro-variations
    """
    params = beziercurve.BezierCurveParams()
    # Ces attributs existent dans pyclick/beziercurve; on laisse par défaut si absents
    for name, val in (("speed", speed), ("overshoot", overshoot), ("noise", noise)):
        if hasattr(params, name):
            setattr(params, name, val)
    beziercurve.set_default_params(params)


def set_seed(seed: Optional[int]) -> None:
    """Fixe la seed RNG (utile pour des tests déterministes)."""
    if seed is None:
        return
    random.seed(seed)


# =========================
#  Helpers "humains"
# =========================
def sleep(base: float = 0.06, jitter: float = 0.04, min_sleep: float = 0.02) -> None:
    """
    Pause pseudo-aléatoire autour de 'base' avec +/- 'jitter'.
    Garantit un temps >= min_sleep.
    """
    t = max(min_sleep, base + random.uniform(-jitter, jitter))
    time.sleep(t)


def point_near(x: int, y: int, jitter: int = 5, gaussian: bool = True) -> Tuple[int, int]:
    """
    Renvoie un point proche de (x,y) avec une dispersion 'humaine'.
    - gaussian=True -> distribution normale (plus réaliste)
    - gaussian=False -> uniforme dans [-jitter, +jitter]
    """
    if jitter <= 0:
        return x, y

    if gaussian:
        # sigma ~ jitter/2 (float) pour éviter les valeurs trop extrêmes
        sigma = max(0.5, jitter / 2.0)
        dx = int(round(random.gauss(0.0, sigma)))
        dy = int(round(random.gauss(0.0, sigma)))
    else:
        dx = random.randint(-jitter, jitter)
        dy = random.randint(-jitter, jitter)
    return x + dx, y + dy


def move(x: int, y: int, jitter: int = 0) -> Tuple[int, int]:
    """
    Déplace la souris vers (x,y) en **pixels écran**.
    - Si jitter > 0 : ajoute un petit bruit humain.
    - Si jitter = 0 : va exactement à la coordonnée demandée.
    """
    if jitter > 0:
        rx, ry = point_near(x, y, jitter=jitter, gaussian=True)
    else:
        rx, ry = x, y

    _set_cursor_pos(rx, ry)
    return rx, ry



def move_click(
    x: int,
    y: int,
    jitter: int = 0,
    delay_range: Tuple[float, float] = (0.04, 0.15),
    button: Literal["left", "right", "middle", "mouse4", "mouse5"] = "left",
) -> Tuple[int, int]:
    """
    Déplace la souris puis clique.
    - Par défaut : clique exactement sur (x,y).
    - Si jitter > 0 : ajoute une variation "humaine".
    """
    rx, ry = move(x, y, jitter=jitter)
    time.sleep(random.uniform(*delay_range))
    interception.click(button=button)
    return rx, ry


def click(
    button: Literal["left", "right", "middle", "mouse4", "mouse5"] = "left",
    delay_range: Tuple[float, float] = (0.035, 0.18),
) -> None:
    """Clic avec un délai humain aléatoire avant l'action."""
    time.sleep(random.uniform(*delay_range))
    interception.click(button=button)


def drag(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    start_jitter: int = 5,
    end_jitter: int = 6,
    pre_delay: Tuple[float, float] = (0.03, 0.12),
    hold_delay: Tuple[float, float] = (0.05, 0.2),
    post_delay: Tuple[float, float] = (0.03, 0.15),
    button: Literal["left", "right", "middle", "mouse4", "mouse5"] = "left",
) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """
    Drag & drop humain:
      - se place près du point A (jitter)
      - attend un court délai (pre_delay)
      - appuie (mouse_down), tient un peu (hold_delay)
      - se déplace jusqu’à près du point B (jitter)
      - relâche (mouse_up) après post_delay
    Retourne ((rx1, ry1), (rx2, ry2)) positions réelles utilisées.
    """
    rx1, ry1 = move(x1, y1, jitter=start_jitter)
    time.sleep(random.uniform(*pre_delay))
    interception.mouse_down(button=button)
    time.sleep(random.uniform(*hold_delay))

    rx2, ry2 = move(x2, y2, jitter=end_jitter)
    time.sleep(random.uniform(*post_delay))
    interception.mouse_up(button=button)

    return (rx1, ry1), (rx2, ry2)


# =========================
#  Démo rapide
# =========================
if __name__ == "__main__":
    # Exemple: move+click “humain” vers (1000,700)
    pos = move_click(1000, 700, jitter=5, delay_range=(0.04, 0.15), button="left")
    print("Clicked near:", pos)

    # Exemple: drag “humain”
    # drag_pos = drag(800, 600, 1200, 650)
    # print("Dragged from-to:", drag_pos)
