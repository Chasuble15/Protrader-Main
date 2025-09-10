# utils/keyboard.py
# Requirements:
#   pip install interception-python
#   (optional) pip install pyperclip
#   -> Install the Interception driver (reboot required)
#   -> Run scripts with Administrator rights

from __future__ import annotations
import time
import random
from typing import Iterable, List, Optional, Tuple, Literal

import interception

try:
    import pyperclip  # optional
except Exception:  # pragma: no cover
    pyperclip = None  # fallback later if not available

__all__ = [
    "set_seed",
    "human_sleep",
    "key_down",
    "key_up",
    "press_key",
    "hotkey",
    "type_text",
    "paste_text",
]

# =========================
#  Global initialization
# =========================
# Capture keyboard automatically (like for mouse)
interception.auto_capture_devices(keyboard=True)

# Common aliases for special keys that interception-python recognizes as strings.
# You can extend this list depending on what you need in your app.
SpecialKey = Literal[
    "enter", "esc", "escape", "tab", "backspace", "space",
    "shift", "ctrl", "control", "alt", "menu",
    "win", "super",
    "up", "down", "left", "right",
    "home", "end", "pgup", "pgdn", "pageup", "pagedown",
    "insert", "delete",
    "capslock", "numlock", "scrolllock",
    "f1","f2","f3","f4","f5","f6","f7","f8","f9","f10","f11","f12"
]


# =========================
#  RNG / timing helpers
# =========================
def set_seed(seed: Optional[int]) -> None:
    """Set RNG seed (useful for deterministic tests)."""
    if seed is not None:
        random.seed(seed)


def human_sleep(base: float = 0.06, jitter: float = 0.04, min_sleep: float = 0.01) -> None:
    """Pause around 'base' seconds with +/- jitter."""
    t = max(min_sleep, base + random.uniform(-jitter, jitter))
    time.sleep(t)


# =========================
#  Low-level key actions
# =========================
def key_down(key: str | SpecialKey) -> None:
    """Hold a key down."""
    interception.key_down(key)


def key_up(key: str | SpecialKey) -> None:
    """Release a held key."""
    interception.key_up(key)


def press_key(key: str | SpecialKey, delay_range: Tuple[float, float] = (0.02, 0.08)) -> None:
    """Press a key with a small human-like delay."""
    human_sleep(random.uniform(*delay_range), 0.0)
    interception.press(key)


def hotkey(keys: Iterable[str | SpecialKey], down_up_gap: Tuple[float, float] = (0.015, 0.06)) -> None:
    """
    Trigger a hotkey combo, e.g. hotkey(["ctrl", "c"]) or hotkey(["ctrl","shift","esc"]).
    Presses keys in order, releases in reverse order.
    """
    seq: List[str] = list(keys)
    for k in seq:
        interception.key_down(k)
        human_sleep(random.uniform(*down_up_gap), 0.0)
    # brief hold
    human_sleep(random.uniform(*down_up_gap), 0.0)
    for k in reversed(seq):
        interception.key_up(k)
        human_sleep(random.uniform(*down_up_gap), 0.0)


# =========================
#  Human-like typing
# =========================
def _pause_for_char(ch: str) -> None:
    """
    Timing heuristic per character:
    - letters/digits: short delay
    - whitespace: a bit longer
    - punctuation: slightly longer
    """
    if ch.isspace():
        human_sleep(base=0.09, jitter=0.05, min_sleep=0.02)
    elif ch.isalnum():
        human_sleep(base=0.06, jitter=0.035, min_sleep=0.015)
    else:
        # punctuation/symbols often take a tad longer
        human_sleep(base=0.08, jitter=0.05, min_sleep=0.02)


def _maybe_make_typo_and_fix(typo_rate: float) -> bool:
    """
    Randomly decide to make a typo (press a random nearby key) and then backspace it.
    Returns True if a typo was performed (so caller can add an extra pause).
    """
    if random.random() < max(0.0, min(typo_rate, 0.5)):
        # crude random wrong char (you can customize with real keyboard adjacency if needed)
        wrong = random.choice("abcdefghijklmnopqrstuvwxyz")
        interception.press(wrong)
        human_sleep(base=0.03, jitter=0.02, min_sleep=0.01)
        interception.press("backspace")
        human_sleep(base=0.04, jitter=0.03, min_sleep=0.01)
        return True
    return False


def type_text(
    text: str,
    *,
    wpm: Tuple[int, int] = (250, 340),
    typo_rate: float = 0.02,
    burst_pause: Tuple[float, float] = (0.25, 0.65),
    punctuation_pause: Tuple[float, float] = (0.12, 0.28),
) -> None:
    """
    Type text with human-like rhythm.
    - wpm: words per minute range (affects base delay variability).
    - typo_rate: probability to insert a small mistake then correct it.
    - burst_pause: occasional longer pause between bursts of characters.
    - punctuation_pause: extra pause after .,!?;: etc.

    Notes:
    - We rely on interception.press(<char or key name>) for each char/special.
    - For uppercase letters, interception.press('A') is typically fine;
      if needed, you can switch to explicit Shift+letter logic.
    """
    # derive small base delay from WPM (very approximate: 1 word ~ 5 chars)
    target_wpm = random.randint(*wpm)
    cps = max(5.0, (target_wpm * 5) / 60.0)  # chars per second
    # base around 1/cps with some variability
    base_delay = 1.0 / cps

    burst_len = random.randint(8, 20)
    since_last_burst = 0

    for ch in text:
        # occasionally insert a typo & fix
        did_typo = _maybe_make_typo_and_fix(typo_rate)

        interception.press(ch)

        # char-level pause
        _pause_for_char(ch)

        # extra pause after sentence punctuation
        if ch in ".!?;:":
            human_sleep(random.uniform(*punctuation_pause), 0.0)

        # random micro jitter around base_delay
        human_sleep(base=base_delay, jitter=base_delay * 0.6, min_sleep=0.005)

        # burst logic (simulate taking a breath)
        since_last_burst += 1
        if since_last_burst >= burst_len or did_typo:
            if random.random() < 0.2 or did_typo:
                human_sleep(random.uniform(*burst_pause), 0.0)
                burst_len = random.randint(8, 20)
                since_last_burst = 0


# =========================
#  Clipboard-based paste
# =========================
def paste_text(text: Optional[str] = None) -> None:
    """
    Paste text into the active control.
    - If 'text' is provided and pyperclip is installed, copies to clipboard then presses Ctrl+V.
    - If 'text' is None, just sends Ctrl+V (assumes your clipboard already has the content).
    """
    if text is not None and pyperclip is not None:
        try:
            pyperclip.copy(text)
            time.sleep(0.02)  # slight pause to ensure clipboard is set
        except Exception:
            # Fallback: type the text if clipboard fails
            type_text(text)
            return
    elif text is not None and pyperclip is None:
        # No pyperclip; fallback to typing
        type_text(text)
        return

    hotkey(["ctrl", "v"])
