"""
EN: Legacy file. In the pre-CDP architecture this class opened its own
    WebSocket to the game server. In the current CDP relay architecture
    it is only used as a callback container by main.py.
ES: Archivo legado. En la arquitectura previa al CDP esta clase abria su
    propio WebSocket al servidor del juego. En la arquitectura actual de
    relay CDP solo se usa como contenedor de callbacks por main.py.
"""

import threading

import websocket as _ws_mod
from pygge.gge_socket import GgeSocket


# EN: Legacy monkey-patch. Forces Chrome-like headers on any WebSocket
#     opened by pygge. Kept for backwards compatibility; not used by the
#     current CDP relay pipeline.
# ES: Monkey-patch legado. Fuerza headers tipo Chrome en cualquier
#     WebSocket abierto por pygge. Se mantiene por compatibilidad; no lo
#     usa el pipeline actual de relay CDP.
_orig_wsapp_init = _ws_mod.WebSocketApp.__init__


def _patched_wsapp_init(self, url, *args, **kwargs):
    headers = list(kwargs.get("header", []) or [])
    headers.extend([
        "Origin: https://empire-html5.goodgamestudios.com",
        "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "Accept-Language: es-419,es;q=0.9",
        "Cache-Control: no-cache",
        "Pragma: no-cache",
    ])
    kwargs["header"] = headers
    _orig_wsapp_init(self, url, *args, **kwargs)


_ws_mod.WebSocketApp.__init__ = _patched_wsapp_init


class GgeSocketBrowser(GgeSocket):
    """
    EN: Callback holder. main.py passes on_send / on_open / on_message /
        on_error / on_close, which are then called by the CDP relay.
    ES: Contenedor de callbacks. main.py pasa on_send / on_open /
        on_message / on_error / on_close, que luego el relay CDP llama.
    """

    def __new__(cls, *args, **kwargs):
        return super().__new__(cls, "ep-", None, *args, **kwargs)

    def __init__(
        self, on_send=None, on_open=None, on_message=None, on_error=None, on_close=None
    ):
        self.onsend = on_send
        self.onopen = on_open
        self.onmessage = on_message
        self.onerror = on_error
        self.onclose = on_close
        self.ws_server = None
        # EN: Set by connect_with_browser once the relay is ready.
        # ES: Lo setea connect_with_browser cuando el relay esta listo.
        self.cdp_relay = None

    # EN: Legacy methods below. Kept for backwards compatibility only.
    # ES: Metodos legados. Se mantienen solo por compatibilidad.

    def open(self, url):
        super().__init__(
            url,
            None,
            on_send=self.onsend,
            on_open=self.__onopen,
            on_message=self.__onmessage,
            on_error=self.onerror,
            on_close=self.__onclose,
        )
        threading.Thread(target=self.run_forever, daemon=True).start()

    def set_server_header(self, server_header):
        self.server_header = server_header

    def set_ws_server(self, ws_server):
        self.ws_server = ws_server

    def __onopen(self, ws):
        self.onopen and self.onopen(ws)
        self.ws_server.broadcast_sync(f"open")

    def __onmessage(self, ws, message):
        self.onmessage and self.onmessage(ws, message)
        self.ws_server.broadcast_sync(message.encode("UTF-8"))

    def __onclose(self, ws, close_status_code, close_msg):
        self.onclose and self.onclose(ws, close_status_code, close_msg)
        self.ws_server.close_connections_sync()