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
        # EN: Map of msg_id -> method, to correlate CDP responses with
        #     the command that triggered them (for logging).
        # ES: Mapa de msg_id -> method, para correlacionar respuestas CDP
        #     con el comando que las disparo (para logging).
        self._pending = {}
        # EN: requestId of the game's WebSocket, captured via
        #     Network.webSocketCreated. Kept for diagnostics.
        # ES: requestId del WebSocket del juego, capturado via
        #     Network.webSocketCreated. Se guarda para diagnostico.
        self.game_ws_request_id = None

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
        self._pending[mid] = method
        cmd = {"id": mid, "method": method}
        if params:
            cmd["params"] = params
        self.ws.send(json.dumps(cmd))

    def _on_open(self, ws):
        # EN: Enable Network (for WS frame events) and Runtime (for
        #     Runtime.evaluate, used to inject commands).
        # ES: Habilita Network (para eventos de frames WS) y Runtime (para
        #     Runtime.evaluate, usado para inyectar comandos).
        print("[CDP] Connection open, enabling Network + Runtime", flush=True)
        print("[CDP] Conexion abierta, habilitando Network + Runtime", flush=True)
        self._send_cdp("Network.enable")
        self._send_cdp("Runtime.enable")
        # EN: Install the WebSocket hook shortly after enabling Runtime.
        # ES: Instala el hook del WebSocket poco despues de habilitar Runtime.
        threading.Thread(target=self._install_ws_hook_later, daemon=True).start()

    def _install_ws_hook_later(self):
        """
        EN: Wait a moment for Runtime.enable to be processed, then install
            the WebSocket hook so we can capture game instances.
        ES: Espera un momento a que Runtime.enable sea procesado, luego
            instala el hook del WebSocket para capturar instancias del juego.
        """
        time.sleep(0.7)
        expr = (
            "(function(){"
            "  try {"
            "    if (window.__gge_hooked) {"
            "      return 'ALREADY list=' + (window.__gge_ws_list ? window.__gge_ws_list.length : 0);"
            "    }"
            "    window.__gge_hooked = true;"
            "    window.__gge_ws_list = [];"
            "    try {"
            "      var OrigWS = window.WebSocket;"
            "      var Wrapped = function(url, protocols) {"
            "        var ws = (protocols === undefined) ? new OrigWS(url) : new OrigWS(url, protocols);"
            "        window.__gge_ws_list.push(ws);"
            "        return ws;"
            "      };"
            "      Wrapped.prototype = OrigWS.prototype;"
            "      Wrapped.CONNECTING = OrigWS.CONNECTING;"
            "      Wrapped.OPEN = OrigWS.OPEN;"
            "      Wrapped.CLOSING = OrigWS.CLOSING;"
            "      Wrapped.CLOSED = OrigWS.CLOSED;"
            "      window.WebSocket = Wrapped;"
            "    } catch(e) {}"
            "    try {"
            "      var origSend = WebSocket.prototype.send;"
            "      WebSocket.prototype.send = function() {"
            "        if (window.__gge_ws_list.indexOf(this) === -1) {"
            "          window.__gge_ws_list.push(this);"
            "        }"
            "        return origSend.apply(this, arguments);"
            "      };"
            "    } catch(e) {}"
            "    return 'HOOK_INSTALLED';"
            "  } catch(e) {"
            "    return 'HOOK_ERR: ' + e.message;"
            "  }"
            "})()"
        )
        self._send_cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True})

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
        except Exception:
            return

        # EN: CDP responses have an 'id' and no 'method'. Log them so we
        #     can see what happened with each command we sent.
        # ES: Las respuestas CDP tienen 'id' y no 'method'. Las logueamos
        #     para ver que paso con cada comando que enviamos.
        if "id" in data and "method" not in data:
            mid = data["id"]
            sent = self._pending.pop(mid, "?")
            if "error" in data:
                print(f"[CDP] ERROR {sent} id={mid}: {data['error']}", flush=True)
            elif sent == "Runtime.evaluate":
                r = data.get("result", {}).get("result", {})
                v = r.get("value")
                if v is None:
                    v = f"<{r.get('type', 'unknown')}>"
                print(f"[CDP] Runtime.evaluate id={mid} -> {v}", flush=True)
            return

        method = data.get("method")
        if method == "Network.webSocketCreated":
            # EN: Keep track of the game WebSocket (only for diagnostics).
            # ES: Guarda el WebSocket del juego (solo para diagnostico).
            p = data.get("params", {})
            url = p.get("url", "")
            rid = p.get("requestId")
            if "goodgamestudios.com" in url:
                self.game_ws_request_id = rid
                print(
                    f"[CDP] Game WebSocket created / WebSocket del juego creado: "
                    f"requestId={rid}",
                    flush=True,
                )
        elif method == "Network.webSocketFrameReceived":
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
        EN: Inject a command into the game WebSocket. The game hides its
            socket inside a module closure (window.socket is undefined),
            so we hooked WebSocket.prototype.send earlier. Any frame the
            game sends (e.g. the periodic 'pin') causes our hook to
            register the instance in window.__gge_ws_list. From there,
            we just pick the goodgamestudios one and call .send() on it.
        ES: Inyecta un comando en el WebSocket del juego. El juego esconde
            su socket dentro de un closure (window.socket es undefined),
            asi que antes hookeamos WebSocket.prototype.send. Cualquier
            frame que el juego envie (ej. el 'pin' periodico) hace que
            nuestro hook registre la instancia en window.__gge_ws_list.
            Desde ahi, elegimos la de goodgamestudios y llamamos .send().
        """
        payload_literal = json.dumps(data)
        expr = (
            "(function(){"
            f"  var payload = {payload_literal};"
            "  try {"
            "    var list = window.__gge_ws_list || [];"
            "    for (var i = 0; i < list.length; i++) {"
            "      var ws = list[i];"
            "      try {"
            "        if (ws && ws.readyState === 1 && ws.url && String(ws.url).indexOf('goodgamestudios') !== -1) {"
            "          ws.send(payload);"
            "          return 'OK i=' + i + ' list=' + list.length + ' url=' + String(ws.url).slice(0, 90);"
            "        }"
            "      } catch(e) {}"
            "    }"
            "    var info = [];"
            "    for (var j = 0; j < list.length; j++) {"
            "      try { info.push(String(list[j].url || '?').slice(0, 60) + ' rs=' + list[j].readyState); }"
            "      catch(e) { info.push('?'); }"
            "    }"
            "    return 'NO_WS_YET list=' + list.length + ' [' + info.join(' | ') + ']';"
            "  } catch(e) {"
            "    return 'ERR: ' + e.message;"
            "  }"
            "})()"
        )
        self._send_cdp("Runtime.evaluate", {
            "expression": expr,
            "returnByValue": True,
        })