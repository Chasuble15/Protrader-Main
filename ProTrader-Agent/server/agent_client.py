# pip install websockets psutil
import asyncio
import json
import threading
import time
from typing import Any, Callable, Dict, Optional
from queue import Queue, Empty

import websockets
from utils.logger import get_logger

logger = get_logger(__name__)

class RealtimeClient:
    """
    Client WebSocket qui tourne dans un thread.
    - start() / stop()
    - send(msg: dict) thread-safe
    - on_message(callback) OU get_message(timeout) via queue
    - reconnexion auto avec backoff
    """

    def __init__(
        self,
        server_url: str,
        on_message: Optional[Callable[[Dict[str, Any]], None]] = None,
        ping_interval: float = 20.0,
        max_queue: int = 1000,
    ):
        self.server_url = server_url
        self.on_message_cb = on_message
        self.ping_interval = ping_interval

        # Queues thread-safe
        self._out_q_async: Optional[asyncio.Queue] = None           # côté loop
        self._in_q_thread: Queue = Queue(maxsize=max_queue)         # côté utilisateur

        # Infra thread/loop
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()

        # Connexion courante
        self._ws = None

    # -------------------- API publique --------------------

    def start(self) -> None:
        """Démarre le thread + boucle asyncio."""
        if self._thread and self._thread.is_alive():
            return
        logger.info("Starting realtime client thread")
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._thread_main, name="RealtimeClient", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Arrête proprement."""
        logger.info("Stopping realtime client thread")
        self._stop_evt.set()
        if self._loop:
            # réveiller la loop
            self._call_soon_threadsafe(asyncio.sleep, 0)
        if self._thread:
            self._thread.join(timeout=5)

    def send(self, msg: Dict[str, Any]) -> bool:
        """
        Envoie un message (dict) vers le serveur.
        Thread-safe. Retourne True si le message est queué, False sinon.
        """
        if not isinstance(msg, dict):
            raise TypeError("msg doit être un dict JSON-sérialisable")
        if not self._loop or not self._out_q_async:
            return False
        try:
            def _put():
                try:
                    self._out_q_async.put_nowait(msg)
                    logger.debug("Queued message: %s", msg)
                except asyncio.QueueFull:
                    logger.warning("Outgoing queue full; dropping message")

            self._loop.call_soon_threadsafe(_put)
            return True
        except Exception as e:
            logger.exception("Failed to queue message: %s", e)
            return False

    def get_message(self, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """
        Récupère un message entrant depuis la queue (si pas de callback).
        """
        try:
            return self._in_q_thread.get(timeout=timeout)
        except Empty:
            return None

    def set_on_message(self, cb: Optional[Callable[[Dict[str, Any]], None]]) -> None:
        """Définit/retire le callback de réception."""
        self.on_message_cb = cb

    # -------------------- Thread & loop internes --------------------

    def _thread_main(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._out_q_async = asyncio.Queue(maxsize=1000)
        try:
            self._loop.run_until_complete(self._run())
        finally:
            # fermer proprement
            pending = asyncio.all_tasks(loop=self._loop)
            for t in pending:
                t.cancel()
            try:
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            self._loop.close()

    async def _run(self):
        backoff = 1.0
        while not self._stop_evt.is_set():
            try:
                await self._connect_and_run()
                backoff = 1.0  # si on sort proprement, reset backoff
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._emit_local({"type": "local_error", "msg": str(e)})
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _connect_and_run(self):
        logger.info("Connecting to %s", self.server_url)
        self._emit_local({"type": "local_info", "msg": "connecting"})
        async with websockets.connect(self.server_url, max_size=2**22, ping_interval=self.ping_interval) as ws:
            self._ws = ws
            logger.info("Connected to server")
            self._emit_local({"type": "local_info", "msg": "connected"})

            send_task = asyncio.create_task(self._sender_loop(ws))
            recv_task = asyncio.create_task(self._receiver_loop(ws))
            done, pending = await asyncio.wait(
                {send_task, recv_task},
                return_when=asyncio.FIRST_EXCEPTION
            )
            for t in pending:
                t.cancel()
        self._ws = None
        logger.info("Disconnected from server")
        self._emit_local({"type": "local_info", "msg": "disconnected"})

    async def _sender_loop(self, ws):
        # Envoi périodique d’un ping applicatif optionnel (en plus du ping WS)
        last_ping = time.time()
        while not self._stop_evt.is_set():
            try:
                # priorité aux messages utilisateurs
                try:
                    msg = await asyncio.wait_for(self._out_q_async.get(), timeout=1.0)
                    await ws.send(json.dumps(msg))
                except asyncio.TimeoutError:
                    pass

                # ping applicatif
                if time.time() - last_ping >= 30:
                    await ws.send(json.dumps({"type": "ping", "ts": int(time.time())}))
                    last_ping = time.time()
            except (asyncio.CancelledError, websockets.ConnectionClosed):
                break

    async def _receiver_loop(self, ws):
        async for text in ws:
            try:
                msg = json.loads(text)
            except Exception:
                msg = {"type": "raw", "raw": text}
            logger.debug("Received message: %s", msg)
            self._handle_incoming(msg)

    def _handle_incoming(self, msg: Dict[str, Any]):
        # Callback si défini
        if self.on_message_cb:
            try:
                self.on_message_cb(msg)
            except Exception:
                logger.exception("Error in on_message callback")
        # Pousse aussi dans la queue thread-safe (pour polling si besoin)
        try:
            self._in_q_thread.put_nowait(msg)
        except Exception:
            # si la queue est pleine, on drop le plus vieux pour garder le flux frais
            try:
                _ = self._in_q_thread.get_nowait()
                self._in_q_thread.put_nowait(msg)
            except Exception:
                pass

    def _emit_local(self, msg: Dict[str, Any]):
        # messages d’état locaux
        logger.debug("Local event: %s", msg)
        self._handle_incoming(msg)

    def _call_soon_threadsafe(self, coro_func, *args, **kwargs):
        if self._loop:
            asyncio.run_coroutine_threadsafe(coro_func(*args, **kwargs), self._loop)
