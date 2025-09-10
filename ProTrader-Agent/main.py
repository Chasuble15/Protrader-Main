# agent/main.py
import time
from server.agent_client import RealtimeClient
from settings import SERVER_WS_URL
from handlers.commands import on_message
from core.overlay import OverlayService, RectSpec
from utils.logger import get_logger
import bus

import actions.config_actions
import actions.test


logger = get_logger(__name__)

def run():
    # 1) Démarre l’overlay ici (au boot)
    logger.info("Starting overlay service")
    bus.overlay = OverlayService(fps=30)
    bus.overlay.start()
    bus.overlay.wait_ready()  # IMPORTANT si on dessine juste après
    logger.info("Overlay service started")

    # 2) Démarre le client temps réel
    logger.info("Starting realtime client")
    client = RealtimeClient(SERVER_WS_URL, on_message=on_message)
    bus.client = client
    client.start()
    logger.info("Realtime client started")

    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        pass
    finally:
        logger.info("Shutting down services")
        # Arrêt propre (ordre: client, overlay)
        try:
            client.stop()
            logger.info("Realtime client stopped")
        except Exception:
            logger.exception("Error while stopping realtime client")
        try:
            if bus.overlay:
                bus.overlay.stop()
                logger.info("Overlay service stopped")
        except Exception:
            logger.exception("Error while stopping overlay service")

if __name__ == "__main__":
    run()

