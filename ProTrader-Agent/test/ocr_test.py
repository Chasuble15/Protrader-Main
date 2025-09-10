import time
import cv2
import numpy as np
import pytesseract
from mss import mss
from PIL import Image
import sys
import os

# ----- (Windows) DPI awareness pour éviter les captures floues avec le scaling -----
try:
    import ctypes
    ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass

# ----- CONFIG -----
# Chemin Tesseract si non dans le PATH (Windows)
# Exemple : r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(TESSERACT_PATH):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

LANG = "fra"  # "fra" pour français, "eng+fra" pour multi
PSM = "6"     # Page segmentation mode (6 = assume un bloc de texte)
OEM = "1"     # Engine mode (1 = LSTM) ; 3 = default

# OCR options : ajuste selon ton cas
TESSERACT_CONFIG = f'--oem {OEM} --psm {PSM}'

# Pré-traitement : mets True si tu veux binariser/agrandir
UPSCALE = True
THRESH = True

# Affichage des bounding boxes + conf
DRAW_BOXES = True

# ----- Fonctions utilitaires -----
def select_roi_once(mon):
    """
    Affiche un screenshot de l'écran et permet de sélectionner une ROI.
    Retourne un dict mss {'top','left','width','height'}.
    """
    with mss() as sct:
        # mon=1 => écran principal. Pour multi-moniteurs, adapte l'index.
        monitor = sct.monitors[mon]
        img = np.array(sct.grab(monitor))[:, :, :3]  # BGRA -> BGR
    # OpenCV attend BGR
    clone = img.copy()
    roi = cv2.selectROI("Sélectionne la zone", clone, fromCenter=False, showCrosshair=True)
    cv2.destroyWindow("Sélectionne la zone")
    x, y, w, h = roi
    if w == 0 or h == 0:
        return None
    # Converti en coordonnées globales du moniteur
    return {"left": monitor["left"] + int(x),
            "top": monitor["top"] + int(y),
            "width": int(w),
            "height": int(h)}

def preprocess_for_ocr(frame_bgr):
    """
    Pré-traitement simple pour améliorer l'OCR : niveaux de gris, upscale, threshold.
    """
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    if UPSCALE:
        # Agrandit pour aider l'OCR sur petites polices
        gray = cv2.resize(gray, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_LINEAR)
    if THRESH:
        gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    return gray

def ocr_image(image_gray):
    """
    Retourne:
      - texte concaténé (nettoyé)
      - data pandas-like sous forme de dict (image_to_data)
    """
    # pytesseract accepte un array ou une PIL Image
    text = pytesseract.image_to_string(image_gray, lang=LANG, config=TESSERACT_CONFIG) or ""
    data = pytesseract.image_to_data(image_gray, lang=LANG, config=TESSERACT_CONFIG,
                                     output_type=pytesseract.Output.DICT)
    # Nettoyage texte global
    text_clean = "\n".join([line.strip() for line in text.splitlines() if line.strip()])
    return text_clean, data

def draw_boxes(frame_bgr, data, scale_x=1.0, scale_y=1.0):
    n = len(data.get("text", []))
    for i in range(n):
        conf = safe_int(data["conf"][i], -1)
        txt  = str(data["text"][i]).strip()

        if conf > 50 and txt:
            x = safe_int(data["left"][i], 0)
            y = safe_int(data["top"][i], 0)
            w = safe_int(data["width"][i], 0)
            h = safe_int(data["height"][i], 0)

            # redimensionne vers l’image d’affichage
            x = int(x / scale_x)
            y = int(y / scale_y)
            w = int(w / scale_x)
            h = int(h / scale_y)

            cv2.rectangle(frame_bgr, (x, y), (x+w, y+h), (0, 255, 0), 1)
            cv2.putText(frame_bgr, f'{txt} ({conf})', (x, max(0, y-5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1, cv2.LINE_AA)


def main():
    print("Démarrage OCR temps réel...")
    # Choix du moniteur : 1 = principal (mss.monitors[1])
    MONITOR_INDEX = 1

    roi = select_roi_once(MONITOR_INDEX)
    if roi is None:
        print("Aucune zone sélectionnée. Fermeture.")
        sys.exit(0)

    last_text = None
    fps_last = time.time()
    frames = 0

    with mss() as sct:
        while True:
            # Capture ROI
            sct_img = sct.grab(roi)
            frame = np.array(sct_img)[:, :, :3]  # BGR

            # Copie pour affichage
            display = frame.copy()

            # Pré-traitement pour OCR
            gray = preprocess_for_ocr(frame)
            # ratios entre l’image OCR (gray) et l’image affichée (display)
            scale_x = gray.shape[1] / display.shape[1]
            scale_y = gray.shape[0] / display.shape[0]

            # Calcule le facteur d'échelle si UPSCALE True (affichage vs OCR)
            scale = 1.5 if UPSCALE else 1.0

            # OCR
            text, data = ocr_image(gray)

            # Dessine les boxes sur l'image affichée si demandé
            if DRAW_BOXES and data is not None:
                draw_boxes(display, data, scale_x=scale_x, scale_y=scale_y)

            # Affiche FPS
            frames += 1
            now = time.time()
            if now - fps_last >= 1.0:
                fps = frames / (now - fps_last)
                fps_last = now
                frames = 0
                cv2.setWindowTitle("OCR Zone", f"OCR Zone - {fps:.1f} FPS")

            # Affiche résultat
            cv2.imshow("OCR Zone", display)

            # Log seulement si le texte a changé
            if text and text != last_text:
                print("="*40)
                print(text)
                last_text = text

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('r'):
                cv2.destroyWindow("OCR Zone")
                new_roi = select_roi_once(MONITOR_INDEX)
                if new_roi:
                    roi = new_roi
                cv2.namedWindow("OCR Zone")

    cv2.destroyAllWindows()


def safe_int(x, default=-1):
    if isinstance(x, (int, float)):
        try:
            return int(x)
        except Exception:
            return default
    if isinstance(x, str):
        try:
            # gère "", "-1", "87.5"
            return int(float(x))
        except Exception:
            return default
    return default


if __name__ == "__main__":
    main()
