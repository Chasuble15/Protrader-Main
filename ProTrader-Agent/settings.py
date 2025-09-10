# agent/settings.py
import os
from pathlib import Path

# URL du websocket serveur (peut venir d'une variable d'env)
SERVER_WS_URL = os.getenv("AGENT_SERVER_WS", "wss://pc.srv539174.hstgr.cloud/ws/agent")

# Emplacement du config.yaml (modifiable via env si besoin)
CONFIG_PATH = Path(os.getenv("AGENT_CONFIG_PATH", "config.yaml")).resolve()
