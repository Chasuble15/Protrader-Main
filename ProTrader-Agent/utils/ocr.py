# ocr.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, Literal, List

import cv2
import mss
import numpy as np

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ocr_read_int(
    region: Tuple[int, int, int, int],
    *,
    monitor_index: int = 1,
    tesseract_cmd: str = r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    psm: int = 7,
    debug: bool = False,
    debug_ttl: float = 1.2,
    debug_outline=(60, 200, 80, 220),  # vert translucide
    debug_width_px: int = 3,
) -> Optional[int]:
    """
    Lit une chaîne numérique dans la zone (left, top, width, height) et retourne un int.
    - region est relative au moniteur capturé (comme dans ta vision).
    - Utilise pytesseract en whitelist 0-9, psm configurable (7: single line).
    - En debug, dessine la zone dans l'overlay.

    Retourne None si pas de lecture fiable.
    """
    roi_bgr, (off_x, off_y) = _grab_and_crop(monitor_index, region)

    # Pipeline OCR multi-essais (prétraitements simples)
    best_val, best_conf = None, -1.0
    for variant in _preprocess_variants(roi_bgr):
        text, conf = _tesseract_digits(variant, tesseract_cmd=tesseract_cmd, psm=psm)
        val = _parse_int(text)
        if val is not None and conf > best_conf:
            best_val, best_conf = val, conf

    # Overlay debug
    if debug:
        _overlay_rect(
            left=off_x, top=off_y,
            width=roi_bgr.shape[1], height=roi_bgr.shape[0],
            ttl=debug_ttl, outline=debug_outline, width_px=debug_width_px,
            label=f"OCR: {best_val if best_val is not None else 'None'} (conf≈{best_conf:.0f})"
        )

    return best_val


def ocr_try_read_ints(
    region: Tuple[int, int, int, int],
    *,
    monitor_index: int = 1,
    tesseract_cmd: str = r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    psm_candidates: Tuple[int, ...] = (7, 8, 6),
    max_results: int = 3,
) -> List[Tuple[int, float, int]]:
    """
    Variante qui renvoie les meilleurs candidats [(value, confidence, psm)], triés par confiance.
    Utile pour calibrer rapidement.
    """
    roi_bgr, _ = _grab_and_crop(monitor_index, region)

    cands: List[Tuple[int, float, int]] = []
    for psm in psm_candidates:
        for variant in _preprocess_variants(roi_bgr):
            text, conf = _tesseract_digits(variant, tesseract_cmd=tesseract_cmd, psm=psm)
            val = _parse_int(text)
            if val is not None:
                cands.append((val, conf, psm))

    cands.sort(key=lambda t: t[1], reverse=True)
    return cands[:max_results]


# ---------------------------------------------------------------------------
# Screen capture & region crop (identique esprit à ta vision)
# ---------------------------------------------------------------------------

def _grab_screen(monitor_index: int = 1) -> Tuple[np.ndarray, int, int]:
    """Retourne (frame BGR, mon_left, mon_top)."""
    with mss.mss() as sct:
        monitors = sct.monitors
        if monitor_index < 1 or monitor_index >= len(monitors):
            monitor_index = 1
        mon = monitors[monitor_index]
        shot = np.array(sct.grab(mon))
        frame = shot[..., :3]  # BGR
        return frame, int(mon["left"]), int(mon["top"])

def _crop_region(img: np.ndarray, region: Optional[Tuple[int, int, int, int]]) -> Tuple[np.ndarray, Tuple[int, int]]:
    """Rogne l'image à region=(l,t,w,h) (coords relatives à img). Retourne (roi, (off_x, off_y))."""
    if not region:
        return img, (0, 0)
    l, t, w, h = region
    h_img, w_img = img.shape[:2]
    l2 = max(0, min(w_img - 1, l))
    t2 = max(0, min(h_img - 1, t))
    r2 = max(0, min(w_img, l + w))
    b2 = max(0, min(h_img, t + h))
    if r2 <= l2 or b2 <= t2:
        raise ValueError("Region hors de l'image")
    return img[t2:b2, l2:r2], (l2, t2)

def _grab_and_crop(monitor_index: int, region: Tuple[int, int, int, int]) -> Tuple[np.ndarray, Tuple[int, int]]:
    """Capture l'écran puis rogne la zone; retourne (roi_bgr, (off_x_abs, off_y_abs))."""
    screen_bgr, mon_left, mon_top = _grab_screen(monitor_index)
    roi_bgr_rel, (off_x_rel, off_y_rel) = _crop_region(screen_bgr, region)
    # convertit l'offset relatif en coord. absolues pour overlay
    return roi_bgr_rel, (mon_left + off_x_rel, mon_top + off_y_rel)


# ---------------------------------------------------------------------------
# OCR core
# ---------------------------------------------------------------------------

def _tesseract_digits(img_bgr: np.ndarray, *, tesseract_cmd: Optional[str], psm: int) -> Tuple[str, float]:
    """
    Lance pytesseract sur img_bgr, whitelist=digits, renvoie (texte, conf_moyenne_approx).
    Si pytesseract absent, raise avec message clair.
    """
    try:
        import pytesseract
        from pytesseract import Output
    except Exception as e:
        raise RuntimeError(
            "pytesseract n'est pas disponible. Installe-le (pip install pytesseract) "
            "et installe Tesseract (Windows: C:\\Program Files\\Tesseract-OCR\\tesseract.exe)."
        ) from e

    if tesseract_cmd:
        import pytesseract as _pt
        _pt.pytesseract.tesseract_cmd = tesseract_cmd

    config = f'--psm {psm} -c tessedit_char_whitelist=0123456789'
    data = pytesseract.image_to_data(img_bgr, output_type=Output.DICT, config=config)

    # Concatène uniquement les tokens contenant des chiffres
    tokens = []
    confs = []
    for txt, conf in zip(data["text"], data["conf"]):
        if txt and any(ch.isdigit() for ch in txt):
            tokens.append(txt)
            try:
                c = float(conf)
            except Exception:
                c = -1.0
            if c >= 0:
                confs.append(c)

    text = "".join(tokens).strip()
    avg_conf = float(np.mean(confs)) if confs else -1.0
    return text, avg_conf


def _parse_int(text: str) -> Optional[int]:
    """Ne garde que les chiffres; retourne int ou None."""
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    # Retire les zéros de tête uniquement si tout n'est pas zéro
    try:
        return int(digits)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Preprocess variants (légers, efficaces)
# ---------------------------------------------------------------------------

def _preprocess_variants(bgr: np.ndarray) -> List[np.ndarray]:
    """
    Génère quelques variantes de pré-traitement pour améliorer l'OCR.
    Retourne des images BGR (Tesseract accepte BGR/RGB/GRAY).
    """
    out: List[np.ndarray] = []

    # 1) upscale x2 + gris + Otsu (BINARY)
    v1 = _prep_one(bgr, scale=2.0, invert=False)
    out.append(v1)

    # 2) idem mais invert
    v2 = _prep_one(bgr, scale=2.0, invert=True)
    out.append(v2)

    # 3) CLAHE + thresh normal
    v3 = _prep_one(bgr, scale=1.8, invert=False, clahe=True)
    out.append(v3)

    # 4) CLAHE + invert
    v4 = _prep_one(bgr, scale=1.8, invert=True, clahe=True)
    out.append(v4)

    # 5) léger blur + morph close (bouchage des trous)
    v5 = _prep_one(bgr, scale=2.0, invert=False, blur=True, morph_close=True)
    out.append(v5)

    return out


def _prep_one(
    bgr: np.ndarray,
    *,
    scale: float = 2.0,
    invert: bool = False,
    clahe: bool = False,
    blur: bool = False,
    morph_close: bool = False,
) -> np.ndarray:
    """Construit une variante fortement lisible pour chiffres."""
    img = bgr
    if scale != 1.0:
        interp = cv2.INTER_CUBIC if scale > 1.0 else cv2.INTER_AREA
        img = cv2.resize(img, (0, 0), fx=scale, fy=scale, interpolation=interp)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    if clahe:
        c = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = c.apply(gray)

    if blur:
        gray = cv2.GaussianBlur(gray, (3, 3), 0)

    # Otsu + option invert
    thresh_type = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
    _, th = cv2.threshold(gray, 0, 255, thresh_type | cv2.THRESH_OTSU)

    if morph_close:
        k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, k, iterations=1)

    # Tesseract accepte le GRAY, mais on renvoie BGR pour rester homogène
    bgr_out = cv2.cvtColor(th, cv2.COLOR_GRAY2BGR)
    return bgr_out


# ---------------------------------------------------------------------------
# Overlay (optionnel)
# ---------------------------------------------------------------------------

def _overlay_rect(
    left: int, top: int, *, width: int, height: int,
    ttl: float, outline: Tuple[int, int, int, int], width_px: int,
    label: Optional[str] = None,
) -> None:
    """Dessine un cadre via ton overlay existant, sans casser si indisponible."""
    try:
        from core.overlay import RectSpec
        import bus
        ov = getattr(bus, "overlay", None)
        if ov:
            ov.add_rect(
                RectSpec(
                    left,
                    top,
                    left + width,
                    top + height,
                    fill_rgba=None,
                    outline_rgba=outline,
                    width=width_px,
                    ttl=ttl
                )
            )
    except Exception:
        # Le debug overlay ne doit jamais bloquer l'OCR
        pass


