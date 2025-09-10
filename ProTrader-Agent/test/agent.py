import time
from server.agent_client import RealtimeClient

SERVER = "wss://pc.srv539174.hstgr.cloud/ws/agent"

def on_msg(msg):
    # Ici tu reçois tout ce que le backend (et donc l’UI) t’envoie en retour,
    # par ex. les commandes, acks, etc. (si tu veux traiter en callback)
    print("[on_message]", msg)

client = RealtimeClient(SERVER, on_message=on_msg)
client.start()

# Exemple : envoyer périodiquement ta frame d’affichage depuis "n'importe où" dans ton code:
import psutil, time

try:
    i = 0
    while True:
        frame = {
            "type": "display",
            "ts": int(time.time()),
            "channel": "main",
            "data": {
                "headline": "Etat machine",
                "cpu": psutil.cpu_percent(),
                "mem": psutil.virtual_memory().percent,
                "step": i % 7,
                "progress": (i % 100)
            }
        }
        ok = client.send(frame)
        if not ok:
            print("send() a échoué (pas encore connecté ?)")

        # Alternative si tu préfères poller au lieu d’un callback :
        # msg = client.get_message(timeout=0.0)
        # if msg: print("reçu:", msg)

        i += 1
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    client.stop()
