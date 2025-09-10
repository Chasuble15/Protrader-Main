# pip install pywin32 pillow numpy
import time
import threading
import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
from typing import Tuple, List, Optional
from queue import Queue, Empty

from PIL import Image, ImageDraw
import win32api, win32con, win32gui
import numpy as np
from utils.logger import get_logger

logger = get_logger(__name__)

# ===== Structures/consts (ctypes) =====
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", ctypes.c_uint32 * 3),
    ]

class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_ubyte),
        ("BlendFlags", ctypes.c_ubyte),
        ("SourceConstantAlpha", ctypes.c_ubyte),
        ("AlphaFormat", ctypes.c_ubyte),
    ]

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

gdi32 = ctypes.windll.gdi32
user32 = ctypes.windll.user32

BI_RGB = 0
DIB_RGB_COLORS = 0
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
ULW_ALPHA = 0x00000002

WS_EX_LAYERED     = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST     = 0x00000008
WS_EX_TOOLWINDOW  = 0x00000080
WS_POPUP          = 0x80000000

# ===== Types dessin =====
@dataclass
class RectSpec:
    x1: int
    y1: int
    x2: int
    y2: int
    fill_rgba: Optional[Tuple[int,int,int,int]] = None
    outline_rgba: Optional[Tuple[int,int,int,int]] = (255, 0, 0, 200)
    width: int = 3
    ttl: Optional[float] = None
    _t0: float = field(default_factory=time.time, repr=False)

    def expired(self) -> bool:
        return self.ttl is not None and (time.time() - self._t0) >= self.ttl

# ===== Service Overlay =====
class OverlayService:
    """
    Overlay click-through, topmost, fixé sur le moniteur principal.
    API thread-safe:
      - start(), stop(), wait_ready()
      - add_rect(RectSpec), add_rect_screen(...)
      - clear(), set_rects(List[RectSpec])
    """
    def __init__(self, fps: int = 30):
        self._fps = fps
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._cmd_q: Queue = Queue()
        self._rects: List[RectSpec] = []

        # Win handles (créés dans le thread)
        self._hwnd = None
        self._hdc_screen = None
        self._hdc_mem = None
        self._hbmp = None
        self._vx = self._vy = self._vw = self._vh = 0

    # ------- API publique -------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        logger.info("Starting overlay thread")
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="OverlayService", daemon=True)
        self._thread.start()

    def wait_ready(self, timeout: float = 2.0) -> bool:
        return self._ready.wait(timeout)

    def stop(self):
        if not self._thread:
            return
        logger.info("Stopping overlay thread")
        self._cmd_q.put(("__quit__", None))
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._thread = None

    def add_rect(self, rect: RectSpec):
        self._cmd_q.put(("add_rect", rect))

    def clear(self):
        self._cmd_q.put(("clear", None))

    def set_rects(self, rects: List[RectSpec]):
        self._cmd_q.put(("set_rects", rects))

    def add_rect_screen(self, left: int, top: int, width: int, height: int,
                        *, outline=(255, 0, 0, 220), fill=None, width_px=3, ttl: float = 1.0):
        # queue: conversion en repère overlay faite dans le thread UI
        self._cmd_q.put(("add_rect_screen", (int(left), int(top), int(width), int(height),
                                             outline, fill, int(width_px), float(ttl))))

    # ------- Thread principal Overlay -------
    def _init_window(self):
        # DPI per-monitor (meilleur alignement multi-écrans)
        try:
            user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
        except Exception:
            try:
                user32.SetProcessDPIAware()
            except Exception:
                pass

        # Géométrie du bureau
        rect = wintypes.RECT()
        user32.GetWindowRect(user32.GetDesktopWindow(), ctypes.byref(rect))
        self._vx = int(rect.left)
        self._vy = int(rect.top)
        self._vw = int(rect.right - rect.left)
        self._vh = int(rect.bottom - rect.top)

        wc = win32gui.WNDCLASS()
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.lpszClassName = "PyOverlayLayered_Service"
        wc.lpfnWndProc = self._wndproc
        try:
            win32gui.RegisterClass(wc)
        except win32gui.error:
            pass  # déjà enregistré

        exstyle = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW
        style   = WS_POPUP

        self._hwnd = win32gui.CreateWindowEx(
            exstyle, wc.lpszClassName, "",
            style, self._vx, self._vy, self._vw, self._vh, 0, 0, wc.hInstance, None
        )

        win32gui.SetWindowPos(self._hwnd, win32con.HWND_TOPMOST,
                              self._vx, self._vy, self._vw, self._vh,
                              win32con.SWP_SHOWWINDOW)

        self._hdc_screen = user32.GetDC(0)
        self._hdc_mem = gdi32.CreateCompatibleDC(self._hdc_screen)

        logger.info("hwnd=%s at (%s,%s) size %sx%s", self._hwnd, self._vx, self._vy, self._vw, self._vh)
        self._ready.set()  # prêt à dessiner

    def _cleanup(self):
        if self._hbmp:
            gdi32.DeleteObject(self._hbmp)
            self._hbmp = None
        if self._hdc_mem:
            gdi32.DeleteDC(self._hdc_mem)
            self._hdc_mem = None
        if self._hdc_screen:
            user32.ReleaseDC(0, self._hdc_screen)
            self._hdc_screen = None
        if self._hwnd:
            try:
                win32gui.DestroyWindow(self._hwnd)
            except Exception:
                pass
            self._hwnd = None
        self._ready.clear()

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == win32con.WM_NCHITTEST:
            return win32con.HTTRANSPARENT  # click-through
        elif msg == win32con.WM_DISPLAYCHANGE:
            return 0
        elif msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _draw_frame(self) -> Image.Image:
        # purge TTL
        self._rects = [r for r in self._rects if not r.expired()]
        img = Image.new("RGBA", (self._vw, self._vh), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for r in self._rects:
            if r.fill_rgba:
                d.rectangle([r.x1, r.y1, r.x2, r.y2], fill=r.fill_rgba)
            if r.outline_rgba and r.width > 0:
                d.rectangle([r.x1, r.y1, r.x2, r.y2], outline=r.outline_rgba, width=r.width)
        return img

    def _blit_image(self, img: Image.Image):
        # 1) RGBA -> BGRA prémultiplié (critique)
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        arr = np.asarray(img, dtype=np.uint8)  # (H,W,4) RGBA
        if arr.shape[0] != self._vh or arr.shape[1] != self._vw:
            img = img.resize((self._vw, self._vh), resample=Image.BILINEAR)
            arr = np.asarray(img, dtype=np.uint8)

        a = arr[..., 3:4].astype(np.uint16)
        rgb = arr[..., :3].astype(np.uint16)
        rgb_pm = (rgb * a + 127) // 255
        bgra_pm = np.dstack((rgb_pm[..., 2], rgb_pm[..., 1], rgb_pm[..., 0], a.squeeze(-1))).astype(np.uint8)
        buf = bgra_pm.tobytes()

        # 2) DIB section
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = self._vw
        bmi.bmiHeader.biHeight = -self._vh  # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB

        bits_ptr = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(
            self._hdc_mem,
            ctypes.byref(bmi),
            DIB_RGB_COLORS,
            ctypes.byref(bits_ptr),
            None,
            0
        )
        if not hbmp:
            raise RuntimeError("CreateDIBSection failed")

        ctypes.memmove(bits_ptr, buf, len(buf))
        oldbmp = gdi32.SelectObject(self._hdc_mem, hbmp)

        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        pt_pos = POINT(self._vx, self._vy)
        size = SIZE(self._vw, self._vh)
        pt_src = POINT(0, 0)

        ok = user32.UpdateLayeredWindow(
            self._hwnd,
            self._hdc_screen,
            ctypes.byref(pt_pos),
            ctypes.byref(size),
            self._hdc_mem,
            ctypes.byref(pt_src),
            0,
            ctypes.byref(blend),
            ULW_ALPHA
        )

        # swap & cleanup
        gdi32.SelectObject(self._hdc_mem, oldbmp)
        if self._hbmp:
            gdi32.DeleteObject(self._hbmp)
        self._hbmp = hbmp
        if not ok:
            raise RuntimeError("UpdateLayeredWindow failed")

        win32gui.SetWindowPos(self._hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                              win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)

    def _screen_to_overlay_rect(self, left: int, top: int, width: int, height: int) -> Tuple[int, int, int, int]:
        x1 = left - self._vx
        y1 = top  - self._vy
        x2 = x1 + width
        y2 = y1 + height
        x1 = max(0, min(self._vw, x1))
        y1 = max(0, min(self._vh, y1))
        x2 = max(0, min(self._vw, x2))
        y2 = max(0, min(self._vh, y2))
        return x1, y1, x2, y2

    def _process_cmd(self, cmd, arg):
        if cmd == "add_rect":
            self._rects.append(arg)

        elif cmd == "add_rect_screen":
            left, top, width, height, outline, fill, width_px, ttl = arg
            x1, y1, x2, y2 = self._screen_to_overlay_rect(left, top, width, height)
            self._rects.append(RectSpec(
                x1=x1, y1=y1, x2=x2, y2=y2,
                outline_rgba=outline, fill_rgba=fill, width=width_px, ttl=ttl
            ))

        elif cmd == "clear":
            self._rects.clear()

        elif cmd == "set_rects":
            self._rects = list(arg)

    def _run(self):
        self._init_window()

        frame_dt = 1.0 / self._fps
        last_t = 0.0

        try:
            while not self._stop.is_set():
                win32gui.PumpWaitingMessages()

                try:
                    while True:
                        cmd, arg = self._cmd_q.get_nowait()
                        if cmd == "__quit__":
                            raise KeyboardInterrupt
                        self._process_cmd(cmd, arg)
                except Empty:
                    pass

                now = time.time()
                if (now - last_t) >= frame_dt:
                    img = self._draw_frame()
                    self._blit_image(img)
                    last_t = now

                time.sleep(0.005)
        except KeyboardInterrupt:
            pass
        finally:
            self._cleanup()
