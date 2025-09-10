# agent/utils/screenshot.py
from typing import Optional, Tuple
import io
import mss
from PIL import Image

def grab_screenshot_base64(
    monitor_index: int = 1,
    region: Optional[Tuple[int,int,int,int]] = None,
    fmt: str = "PNG",
    **kwargs
) -> str:
    with mss.mss() as sct:
        if monitor_index < 1 or monitor_index >= len(sct.monitors):
            monitor_index = 1
        mon = sct.monitors[monitor_index]
        bbox = {"left": mon["left"], "top": mon["top"], "width": mon["width"], "height": mon["height"]}
        if region and isinstance(region, (tuple, list)) and len(region) == 4:
            l, t, w, h = [int(x) for x in region]
            bbox = {"left": l, "top": t, "width": w, "height": h}

        raw = sct.grab(bbox)
        img = Image.frombytes("RGB", raw.size, raw.rgb)  # 1:1 exact

        buf = io.BytesIO()
        if fmt.upper() == "JPEG":
            img.save(buf, format="JPEG", quality=95)
            mime = "image/jpeg"
        else:
            img.save(buf, format="PNG")
            mime = "image/png"

        import base64 as _b64
        b64 = _b64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:{mime};base64,{b64}"
