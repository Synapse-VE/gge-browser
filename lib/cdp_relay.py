"""
EN: CDP relay. Connects to Chrome's debugging port and listens for
    WebSocket frames (both sent and received) via the DevTools Protocol.
    Also allows injecting commands into the game's WebSocket.
ES: Relay CDP. Se conecta al puerto de debug de Chrome y escucha frames
    WebSocket (enviados y recibidos) via el DevTools Protocol.
    Tambien permite inyectar comandos en el WebSocket del juego.
"""

import json
import threading
import time

import requests
import websocket


class CdpRelay:
    """
    EN: Watches and controls the game WebSocket through Chrome DevTools Protocol.
    ES: Observa y controla el WebSocket del juego a traves del Chrome DevTools Protocol.
    """

    def __init__(self, debug_port=9222, on_frame_recv=None, on_frame_sent=None, on_error=None):
        # EN: Chrome remote debugging port. / ES: Puerto de debug remoto de Chrome.
        self.debug_port = debug_port
        # EN: Called for each frame received from the server.
        # ES: Se llama por cada frame recibido del servidor.
        self.on_frame_recv = on_frame_recv
        # EN: Called for each frame sent by the client.
        # ES: Se llama por cada frame enviado por el cliente.
        self.on_frame_sent = on_frame_sent
        # EN: Called when the CDP connection itself errors.
        # ES: Se llama cuando la conexion CDP falla.
        self.on_error = on_error
        self.ws = None
        self.msg_id = 0
        self.lock = threading.Lock()

    def _find_target(self):
        """
        EN: Find the game iframe target in Chrome's debug targets.
        ES: Busca el target del iframe del juego en los targets de debug de Chrome.
        """
        for _ in range(60):
            try:
                r = requests.get(f"http://localhost:{self.debug_port}/json", timeout=2)
                targets = r.json()
                for t in targets:
                    url = t.get("url", "")
                    if "empire-html5.goodgamestudios.com" in url and t.get("webSocketDebuggerUrl"):
                        return t["webSocketDebuggerUrl"]
            except Exception:
                pass
            time.sleep(0.5)
        return None

    def connect(self):
        """
        EN: Connect to the game target and start listening for frames.
        ES: Conecta al target del juego y empieza a escuchar frames.
        """
        url = self._find_target()
        if not url:
            raise RuntimeError("[CDP] Game target not found / No se encontro el target del juego")
        print(f"[CDP] Connecting to / Conectando a {url}", flush=True)

        self.ws = websocket.WebSocketApp(
            url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error_ws,
            on_close=self._on_close,
        )

        def _run():
            # EN: suppress_origin is required because Chrome rejects any
            #     Origin header that is not whitelisted via --remote-allow-origins.
            # ES: suppress_origin es necesario porque Chrome rechaza cualquier
            #     header Origin que no este permitido con --remote-allow-origins.
            self.ws.run_forever(suppress_origin=True)

        threading.Thread(target=_run, daemon=True).start()
        time.sleep(1.5)

    def _send_cdp(self, method, params=None):
        """
        EN: Send a raw CDP command to Chrome.
        ES: Envia un comando CDP crudo a Chrome.
        """
        with self.lock:
            self.msg_id += 1
            mid = self.msg_id
        cmd = {"id": mid, "method": method}
        if params:
            cmd["params"] = params
        self.ws.send(json.dumps(cmd))

    def _on_open(self, ws):
        # EN: Enable the Network domain to receive WebSocket frame events.
        # ES: Habilita el dominio Network para recibir eventos de frames WebSocket.
        print("[CDP] Connection open, enabling Network domain", flush=True)
        print("[CDP] Conexion abierta, habilitando dominio Network", flush=True)
        self._send_cdp("Network.enable")

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
        except Exception:
            return

        method = data.get("method")
        if method == "Network.webSocketFrameReceived":
            p = data.get("params", {})
            resp = p.get("response", {})
            payload = resp.get("payloadData", "")
            if self.on_frame_recv:
                self.on_frame_recv(payload)
        elif method == "Network.webSocketFrameSent":
            p = data.get("params", {})
            resp = p.get("response", {})
            payload = resp.get("payloadData", "")
            if self.on_frame_sent:
                self.on_frame_sent(payload)

    def _on_error_ws(self, ws, error):
        print(f"[CDP] Error: {error}", flush=True)
        if self.on_error:
            self.on_error(error)

    def _on_close(self, ws, code, msg):
        print(f"[CDP] Closed / Cerrado: {code} {msg}", flush=True)

    def send_to_game(self, data):
        """
        EN: Inject a command into the game WebSocket via Runtime.evaluate.
        ES: Inyecta un comando en el WebSocket del juego via Runtime.evaluate.
        """
        expr = f"window.socket && window.socket.send({json.dumps(data)})"
        self._send_cdp("Runtime.evaluate", {"expression": expr})