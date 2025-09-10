"""Simplified vision utilities using OpenCV template matching."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple, Literal

import cv2
import mss
import numpy as np


@dataclass
class MatchResult:
    """Result returned by template matching."""

    left: int
    top: int
    width: int
    height: int
    score: float
    scale: float

    @property
    def bbox(self) -> Tuple[int, int, int, int]:
        return self.left, self.top, self.width, self.height

    @property
    def center(self) -> Tuple[int, int]:
        return self.left + self.width // 2, self.top + self.height // 2


# ---------------------------------------------------------------------------
# Screen capture helpers
# ---------------------------------------------------------------------------
def _grab_screen(monitor_index: int = 1) -> Tuple[np.ndarray, int, int]:
    """Grab the full contents of ``monitor_index`` and return BGR pixels.

    Returns the frame along with the monitor's top-left coordinates.
    """

    with mss.mss() as sct:
        monitors = sct.monitors
        if monitor_index < 1 or monitor_index >= len(monitors):
            monitor_index = 1
        mon = monitors[monitor_index]
        shot = np.array(sct.grab(mon))
        frame = shot[..., :3]
        return frame, int(mon["left"]), int(mon["top"])


def _crop_region(img: np.ndarray, region: Optional[Tuple[int, int, int, int]]) -> Tuple[np.ndarray, Tuple[int, int]]:
    """Crop ``img`` to ``region`` (left, top, width, height).

    Returns the cropped image and the offset applied.
    """

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


def _nms(results: List[MatchResult], iou_thresh: float = 0.3) -> List[MatchResult]:
    """Simple non-maximal suppression on the bounding boxes."""

    if not results:
        return []
    results = sorted(results, key=lambda r: r.score, reverse=True)
    keep: List[MatchResult] = []

    def iou(a: MatchResult, b: MatchResult) -> float:
        ax1, ay1, aw, ah = a.bbox
        bx1, by1, bw, bh = b.bbox
        ax2, ay2 = ax1 + aw, ay1 + ah
        bx2, by2 = bx1 + bw, by1 + bh
        inter_w = max(0, min(ax2, bx2) - max(ax1, bx1))
        inter_h = max(0, min(ay2, by2) - max(ay1, by1))
        inter = inter_w * inter_h
        union = aw * ah + bw * bh - inter
        return inter / union if union > 0 else 0.0

    for r in results:
        if all(iou(r, k) < iou_thresh for k in keep):
            keep.append(r)
    return keep


# ---------------------------------------------------------------------------
# Public API (standard, sans alpha)
# ---------------------------------------------------------------------------
def find_template_on_screen(
    template_path: str,
    *,
    threshold: float = 0.88,
    monitor_index: int = 1,
    region: Optional[Tuple[int, int, int, int]] = None,
    scales: Tuple[float, float, float] = (0.8, 1.25, 1.0),
    use_color: bool = False,
    debug: bool = False,
    debug_draw_mode: Literal["best", "all"] = "best",
    debug_ttl: float = 1.5,
    debug_outline=(255, 80, 0, 230),
    debug_fill=None,
    debug_width_px: int = 3,
) -> Optional[MatchResult]:
    """Return the best match on screen or ``None``.

    Set ``use_color=True`` to perform color-aware template matching instead of the
    default grayscale detection.
    """

    matches = find_all_templates_on_screen(
        template_path,
        threshold=threshold,
        monitor_index=monitor_index,
        region=region,
        max_results=1,
        scales=scales,
        use_color=use_color,
        debug=debug,
        debug_draw_mode=debug_draw_mode,
        debug_ttl=debug_ttl,
        debug_outline=debug_outline,
        debug_fill=debug_fill,
        debug_width_px=debug_width_px,
    )
    return matches[0] if matches else None


def find_all_templates_on_screen(
    template_path: str,
    *,
    threshold: float = 0.88,
    monitor_index: int = 1,
    region: Optional[Tuple[int, int, int, int]] = None,
    max_results: int = 10,
    iou_nms: float = 0.35,
    scales: Tuple[float, float, float] = (0.8, 1.25, 1.0),
    use_color: bool = False,
    debug: bool = False,
    debug_draw_mode: Literal["best", "all"] = "best",
    debug_ttl: float = 1.5,
    debug_outline=(255, 80, 0, 230),
    debug_fill=None,
    debug_width_px: int = 3,
) -> List[MatchResult]:
    """Search ``template_path`` on the screen and return all matches.

    By default both the screenshot and template are converted to grayscale for
    robustness. Pass ``use_color=True`` to match directly on the BGR data for
    color-sensitive detection.
    """

    screen_bgr, _, _ = _grab_screen(monitor_index)
    cropped_bgr, (off_x, off_y) = _crop_region(screen_bgr, region)
    haystack = (
        cropped_bgr
        if use_color
        else cv2.cvtColor(cropped_bgr, cv2.COLOR_BGR2GRAY)
    )

    templ_bgr = cv2.imread(template_path, cv2.IMREAD_COLOR)
    if templ_bgr is None:
        raise FileNotFoundError(f"Template introuvable: {template_path}")
    template_full = (
        templ_bgr if use_color else cv2.cvtColor(templ_bgr, cv2.COLOR_BGR2GRAY)
    )

    start, end, mult = scales
    scale_values: List[float] = [1.0]
    if start > 0 and end > 0 and mult > 1.0:
        scale_values = []
        s = start
        steps = 0
        max_steps = 100
        while s <= end + 1e-9 and steps < max_steps:
            scale_values.append(round(s, 4))
            s *= mult
            steps += 1
        if not scale_values:
            scale_values = [1.0]

    candidates: List[MatchResult] = []
    for s in scale_values:
        tmpl = (
            template_full
            if s == 1.0
            else cv2.resize(template_full, (0, 0), fx=s, fy=s, interpolation=cv2.INTER_AREA)
        )
        if haystack.shape[0] < tmpl.shape[0] or haystack.shape[1] < tmpl.shape[1]:
            continue
        res = cv2.matchTemplate(haystack, tmpl, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(res >= threshold)
        h_t, w_t = tmpl.shape[:2]
        for (y, x) in zip(ys.tolist(), xs.tolist()):
            score = float(res[y, x])
            candidates.append(
                MatchResult(
                    left=int(x + off_x),
                    top=int(y + off_y),
                    width=int(w_t),
                    height=int(h_t),
                    score=score,
                    scale=float(s),
                )
            )

    pruned = _nms(candidates, iou_thresh=iou_nms)
    pruned.sort(key=lambda r: r.score, reverse=True)
    pruned = pruned[:max_results]

    if debug and pruned:
        try:
            from core.overlay import RectSpec  # imported lazily to avoid heavy deps
            import bus

            ov = getattr(bus, "overlay", None)
            if ov:
                to_draw = [pruned[0]] if debug_draw_mode == "best" else pruned
                for r in to_draw:
                    ov.add_rect(
                        RectSpec(
                            r.left,
                            r.top,
                            r.left + r.width,
                            r.top + r.height,
                            fill_rgba=debug_fill,
                            outline_rgba=debug_outline,
                            width=debug_width_px,
                            ttl=debug_ttl,
                        )
                    )
        except Exception:
            # Debug overlay should never break detection
            pass

    return pruned


# ---------------------------------------------------------------------------
# Helpers alpha-bake (simples)
# ---------------------------------------------------------------------------
def _flatten_rgba_to_bgr_on_bg(
    rgba: np.ndarray,
    *,
    bg_bgr: Tuple[int, int, int],
    alpha_min: int = 0,
    crop_to_alpha: bool = True,
) -> np.ndarray:
    """
    Compose un BGRA sur une couleur de fond (BGR) sans gamma-correction :
    out = bgr*alpha + bg*(1-alpha). Optionnellement, rogne au bbox des pixels alpha>alpha_min.
    """
    if rgba is None or rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError("Image RGBA invalide pour le flatten alpha.")

    bgr = rgba[..., :3].astype(np.float32)
    a = rgba[..., 3].astype(np.float32) / 255.0

    if crop_to_alpha:
        mask = (rgba[..., 3] > alpha_min)
        if not np.any(mask):
            # rien d'utile, retourne directement un fond uni 1x1 pour éviter erreurs
            return np.full((1, 1, 3), bg_bgr, dtype=np.uint8)
        ys, xs = np.where(mask)
        y1, y2 = int(ys.min()), int(ys.max()) + 1
        x1, x2 = int(xs.min()), int(xs.max()) + 1
        bgr = bgr[y1:y2, x1:x2]
        a = a[y1:y2, x1:x2]

    bg = np.empty_like(bgr)
    bg[:, :] = np.array(bg_bgr, dtype=np.float32)

    out = bgr * a[..., None] + bg * (1.0 - a[..., None])
    return np.clip(out, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Alpha API : bake simple + détection standard
# ---------------------------------------------------------------------------
def find_template_on_screen_alpha(
    template_path: str,
    *,
    threshold: float = 0.92,
    monitor_index: int = 1,
    region: Optional[Tuple[int, int, int, int]] = None,
    scales: Tuple[float, float, float] = (0.85, 1.2, 1.03),
    use_color: bool = False,
    debug: bool = False,
    debug_draw_mode: Literal["best", "all"] = "best",
    debug_ttl: float = 1.5,
    debug_outline=(255, 80, 0, 230),
    debug_fill=None,
    debug_width_px: int = 3,
    alpha_min: int = 10,
    alpha_bg_bgr: Tuple[int, int, int] = (41, 44, 77),  # BGR du fond (#585E9B)
) -> Optional[MatchResult]:
    """Return the best match with optional alpha handling or ``None``.

    Use ``use_color=True`` for color-aware matching.
    """

    matches = find_all_templates_on_screen_alpha(
        template_path,
        threshold=threshold,
        monitor_index=monitor_index,
        region=region,
        max_results=1,
        iou_nms=0.35,
        scales=scales,
        use_color=use_color,
        debug=debug,
        debug_draw_mode=debug_draw_mode,
        debug_ttl=debug_ttl,
        debug_outline=debug_outline,
        debug_fill=debug_fill,
        debug_width_px=debug_width_px,
        alpha_min=alpha_min,
        alpha_bg_bgr=alpha_bg_bgr,
    )
    return matches[0] if matches else None


def find_all_templates_on_screen_alpha(
    template_path: str,
    *,
    threshold: float = 0.92,
    monitor_index: int = 1,
    region: Optional[Tuple[int, int, int, int]] = None,
    max_results: int = 10,
    iou_nms: float = 0.35,
    scales: Tuple[float, float, float] = (0.85, 1.2, 1.03),
    use_color: bool = False,
    debug: bool = False,
    debug_draw_mode: Literal["best", "all"] = "best",
    debug_ttl: float = 1.5,
    debug_outline=(255, 80, 0, 230),
    debug_fill=None,
    debug_width_px: int = 3,
    alpha_min: int = 10,
    alpha_bg_bgr: Tuple[int, int, int] = (155, 94, 88),  # BGR du fond (#585E9B)
) -> List[MatchResult]:
    """
    1) Lit le template en BGRA.
    2) Remplace l'alpha par une couleur de fond (bake simple).
    3) Détection standard (TM_CCOEFF_NORMED) sur image grise ou couleur selon
       ``use_color``. Pass ``use_color=True`` to match using color information.
    """

    # Écran → éventuellement gris (zone éventuellement rognée)
    screen_bgr, _, _ = _grab_screen(monitor_index)
    cropped_bgr, (off_x, off_y) = _crop_region(screen_bgr, region)
    haystack = (
        cropped_bgr
        if use_color
        else cv2.cvtColor(cropped_bgr, cv2.COLOR_BGR2GRAY)
    )

    # Lecture template (BGRA si dispo)
    templ_rgba = cv2.imread(template_path, cv2.IMREAD_UNCHANGED)
    if templ_rgba is None:
        raise FileNotFoundError(f"Template introuvable: {template_path}")

    # S'il n'y a pas de canal alpha -> pipeline standard
    if not (templ_rgba.ndim == 3 and templ_rgba.shape[2] == 4):
        return find_all_templates_on_screen(
            template_path,
            threshold=threshold,
            monitor_index=monitor_index,
            region=region,
            max_results=max_results,
            iou_nms=iou_nms,
            scales=scales,
            use_color=use_color,
            debug=debug,
            debug_draw_mode=debug_draw_mode,
            debug_ttl=debug_ttl,
            debug_outline=debug_outline,
            debug_fill=debug_fill,
            debug_width_px=debug_width_px,
        )

    # 1) Bake simple (remplacement alpha -> couleur de fond)
    baked_bgr = _flatten_rgba_to_bgr_on_bg(
        templ_rgba,
        bg_bgr=alpha_bg_bgr,
        alpha_min=alpha_min,
        crop_to_alpha=True,
    )

    # 2) Optionnel: gris
    template_full = (
        baked_bgr if use_color else cv2.cvtColor(baked_bgr, cv2.COLOR_BGR2GRAY)
    )

    # 3) Échelles (identiques au standard)
    start, end, mult = scales
    scale_values: List[float] = [1.0]
    if start > 0 and end > 0 and mult and mult > 1.0:
        scale_values = []
        s = start
        steps = 0
        max_steps = 100
        while s <= end + 1e-9 and steps < max_steps:
            scale_values.append(round(s, 4))
            s *= mult
            steps += 1
        if not scale_values:
            scale_values = [1.0]

    # 4) Matching standard (TM_CCOEFF_NORMED)
    candidates: List[MatchResult] = []
    for s in scale_values:
        tmpl = (
            template_full
            if s == 1.0
            else cv2.resize(template_full, (0, 0), fx=s, fy=s, interpolation=cv2.INTER_AREA)
        )
        if haystack.shape[0] < tmpl.shape[0] or haystack.shape[1] < tmpl.shape[1]:
            continue

        res = cv2.matchTemplate(haystack, tmpl, cv2.TM_CCOEFF_NORMED)
        ys2, xs2 = np.where(res >= threshold)
        h_t, w_t = tmpl.shape[:2]
        for (y, x) in zip(ys2.tolist(), xs2.tolist()):
            candidates.append(
                MatchResult(
                    left=int(x + off_x),
                    top=int(y + off_y),
                    width=int(w_t),
                    height=int(h_t),
                    score=float(res[y, x]),
                    scale=float(s),
                )
            )

    # 5) NMS + tri + overlay (comme standard)
    pruned = _nms(candidates, iou_thresh=iou_nms)
    pruned.sort(key=lambda r: r.score, reverse=True)
    pruned = pruned[:max_results]

    if debug and pruned:
        try:
            from core.overlay import RectSpec  # import lazy
            import bus
            ov = getattr(bus, "overlay", None)
            if ov:
                to_draw = [pruned[0]] if debug_draw_mode == "best" else pruned
                for r in to_draw:
                    ov.add_rect(
                        RectSpec(
                            r.left, r.top, r.left + r.width, r.top + r.height,
                            fill_rgba=debug_fill,
                            outline_rgba=debug_outline,
                            width=debug_width_px,
                            ttl=debug_ttl,
                        )
                    )
        except Exception:
            pass

    return pruned


__all__ = [
    "MatchResult",
    "find_template_on_screen",
    "find_all_templates_on_screen",
    "find_template_on_screen_alpha",
    "find_all_templates_on_screen_alpha",
]
