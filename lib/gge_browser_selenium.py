"""
EN: Launches Chrome with the flags needed for the CDP relay to work,
    waits for the game iframe, and connects the relay.
ES: Lanza Chrome con las flags necesarias para el relay CDP,
    espera el iframe del juego, y conecta el relay.
"""

import threading
import traceback
import os
import re
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from lib.cdp_relay import CdpRelay

# EN: Raw log file for auditing every frame without truncation.
# ES: Archivo de log crudo para auditar todos los frames sin truncar.
RAW_LOG = "/tmp/gge_raw.log"
_raw_fp = open(RAW_LOG, "a", buffering=1)


def format_payload(payload, direction):
    """
    EN: Convert a raw WebSocket frame into a human-readable line.
    ES: Convierte un frame WebSocket crudo en una linea legible.
    direction: "RECV" (from server) or "SENT" (from client).
    """
    # EN: Always write the raw frame to file first.
    # ES: Siempre escribimos el frame crudo al archivo primero.
    _raw_fp.write(f"\n=== {direction} ({len(payload)} bytes) ===\n{payload}\n")

    # EN: Base64-encoded binary blob (starts with JXh0 = "%xt" in base64).
    # ES: Blob binario codificado en base64 (empieza con JXh0 = "%xt" en base64).
    if payload.startswith("JXh0"):
        return f"[{direction}] [BIN] base64 payload ({len(payload)} bytes)"

    # EN: SmartFox XML message.
    # ES: Mensaje XML de SmartFox.
    if payload.startswith("<"):
        m = re.match(r"<msg t='(.*?)'><body action='(.*?)' r='(.*?)'>(.*?)</body></msg>", payload)
        if m:
            t, action, r, data = m.groups()
            return f"[{direction}] [XML] t={t} action={action} r={r} data={data[:120]}"
        return f"[{direction}] [XML] {payload[:120]}"

    # EN: EmpireEx protocol: %xt%EmpireEx_NN%<cmd>%<status>%<json>%
    # ES: Protocolo EmpireEx: %xt%EmpireEx_NN%<cmd>%<status>%<json>%
    if payload.startswith("%xt%"):
        parts = payload.strip("%").split("%")
        if len(parts) >= 4:
            cmd = parts[2] if len(parts) > 2 else "?"
            status = parts[3] if len(parts) > 3 else "?"
            data = "%".join(parts[4:]) if len(parts) > 4 else ""

            # EN: Friendly names for the most common commands.
            # ES: Nombres legibles para los comandos mas comunes.
            friendly = {
                "sii": "ServerInfoInit",
                "hgh": "Highscore",
                "ama": "AllianceMembers",
                "irc": "InitResourceCastle",
                "pin": "Ping",
                "llp": "LoginLastPlayer",
                "lli": "LoginInfo",
                "gpi": "GetPlayerInfo",
                "gat": "GetAllianceTasks",
                "all": "AllianceList",
                "asc": "AskCastle",
                "grc": "GetResourcesCastle",
            }.get(cmd, cmd)

            data_preview = data[:200] + ("..." if len(data) > 200 else "")
            return f"[{direction}] [CMD] {friendly} (status={status}) {data_preview}"

    # EN: Unknown format.
    # ES: Formato desconocido.
    return f"[{direction}] [???] {payload[:120]}"


def open_browser(game_url):
    """
    EN: Launch Chrome with the flags required for CDP relay.
    ES: Lanza Chrome con las flags requeridas para el relay CDP.
    """
    port = 9222
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument(f"--user-data-dir={os.path.join(os.getcwd(), 'user-data')}")
    options.add_argument(f"--remote-debugging-port={port}")
    # EN: Required for Chrome to accept the CDP WebSocket connection.
    # ES: Necesario para que Chrome acepte la conexion WebSocket al CDP.
    options.add_argument("--remote-allow-origins=*")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-features=Translate")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("detach", True)

    print("[PY] Launching Chrome... / Lanzando Chrome...", flush=True)
    driver = webdriver.Chrome(options=options)
    print(f"[PY] Chrome: {driver.capabilities.get('browserVersion')}", flush=True)

    driver.switch_to.window(driver.window_handles[-1])
    driver.get(game_url)
    print(f"[PY] Navigated to / Navegando a: {driver.current_url}", flush=True)
    return driver, port


def connect_with_browser(socket, game_url, ws_server_port):
    """
    EN: Launch Chrome, wait for the game iframe, and connect the CDP relay.
        The socket object is only used as a callback container.
    ES: Lanza Chrome, espera el iframe del juego, y conecta el relay CDP.
        El objeto socket solo se usa como contenedor de callbacks.
    """
    driver, debug_port = open_browser(game_url)

    def on_recv(payload):
        # EN: Called for each frame coming from the game server.
        # ES: Se llama por cada frame que llega del servidor del juego.
        try:
            print(format_payload(payload, "RECV"), flush=True)
        except Exception as e:
            print(f"[RECV] <format error: {e}>", flush=True)
        if socket.onmessage:
            try:
                socket.onmessage(None, payload)
            except Exception:
                pass

    def on_sent(payload):
        # EN: Called for each frame the game client sends.
        # ES: Se llama por cada frame que envia el cliente del juego.
        try:
            print(format_payload(payload, "SENT"), flush=True)
        except Exception as e:
            print(f"[SENT] <format error: {e}>", flush=True)
        if socket.onsend:
            try:
                socket.onsend(None, payload)
            except Exception:
                pass

    relay = CdpRelay(
        debug_port=debug_port,
        on_frame_recv=on_recv,
        on_frame_sent=on_sent,
        on_error=lambda e: print(f"[CDP] err: {e}", flush=True),
    )

    def wait_and_connect():
        # EN: Wait for the game iframe, then connect the relay.
        # ES: Espera el iframe del juego, despues conecta el relay.
        print("[PY] Waiting for iframe#game... / Esperando iframe#game...", flush=True)
        try:
            WebDriverWait(driver, 90, poll_frequency=0.5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'iframe#game'))
            )
            print("[PY] iframe found, connecting CDP relay / iframe encontrado, conectando relay CDP", flush=True)
            time.sleep(3)
            relay.connect()
            time.sleep(2)
            if relay.ws and relay.ws.sock and relay.ws.sock.connected:
                print("[PY] CDP relay active. / CDP relay activo.", flush=True)
                print(f"[PY] Raw log / Log crudo: {RAW_LOG}", flush=True)
                socket.cdp_relay = relay
            else:
                print("[PY] CDP relay did not connect properly. / El relay CDP no conecto bien.", flush=True)
                socket.cdp_relay = relay
        except Exception as e:
            print(f"[PY] Error waiting for iframe / Error esperando iframe: {e}", flush=True)
            traceback.print_exc()

    threading.Thread(target=wait_and_connect, daemon=True).start()