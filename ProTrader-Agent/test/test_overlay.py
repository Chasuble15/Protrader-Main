"""Script de test basique pour l'overlay simplifié."""

import time
from core.overlay import OverlayService, RectSpec


def main() -> None:
    ov = OverlayService(fps=30)
    ov.start()
    ov.wait_ready()

    # dessine un cadre rouge persistant
    ov.add_rect(RectSpec(40, 40, 500, 200, outline_rgba=(255, 0, 0, 200), width=4))

    # dessine un rectangle bleu translucide qui disparaît au bout de 2 secondes
    ov.add_rect(RectSpec(100, 250, 500, 420, fill_rgba=(0, 128, 255, 80), ttl=2.0))

    time.sleep(3)

    # remplace tout par une seule zone verte 1.5s
    ov.set_rects([
        RectSpec(300, 300, 800, 600, fill_rgba=(0, 255, 0, 80), outline_rgba=None, ttl=1.5)
    ])

    time.sleep(2)
    ov.clear()

    # garder l’overlay en vie
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        ov.stop()


if __name__ == "__main__":
    main()
