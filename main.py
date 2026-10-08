"""
EN: Entry point. Launches Chrome, connects the CDP relay, and lets the
    user send raw Empire protocol commands from the terminal.
ES: Punto de entrada. Lanza Chrome, conecta el relay CDP, y permite
    enviar comandos crudos del protocolo Empire desde la terminal.
"""

import readline
import sys

import lib.empire_decoder as empire_decoder
from lib.gge_socket_browser import GgeSocketBrowser
from lib.gge_browser_selenium import connect_with_browser
from lib.colors import colors


def print_preserve_input(message):
    """
    EN: Print a message without losing the line currently being typed.
    ES: Imprime un mensaje sin perder la linea que se esta escribiendo.
    """
    input_buf = readline.get_line_buffer()
    sys.stdout.write(f"\x1b[2K\r{message}\n> {input_buf}")
    sys.stdout.flush()


if __name__ == '__main__':
    # EN: Callback container. In the CDP relay architecture this object
    #     does not open a real WebSocket; it only holds callbacks.
    # ES: Contenedor de callbacks. En la arquitectura de relay CDP este
    #     objeto no abre un WebSocket real; solo guarda callbacks.
    socket = GgeSocketBrowser(
        on_send=lambda ws, message: print_preserve_input(colors.LIGHT_GREEN + message + colors.ENDC),
        on_open=lambda ws: print_preserve_input(colors.LIGHT_MAGENTA + 'WebSocket opened' + colors.ENDC),
        on_message=lambda ws, message: print_preserve_input(colors.LIGHT_BLUE + message + colors.ENDC),
        on_error=lambda ws, error: print_preserve_input(colors.LIGHT_RED + f"Error in websocket: {error}" + colors.ENDC),
        on_close=lambda ws, close_status_code, close_msg: print_preserve_input(colors.LIGHT_MAGENTA + f'WebSocket closed with code {close_status_code} and message {close_msg}' + colors.ENDC),
    )

    # EN: Launch Chrome and start the CDP relay.
    # ES: Lanza Chrome y arranca el relay CDP.
    connect_with_browser(
        socket,
        'https://danadum.github.io/empire',
        8765,
    )

    # EN: REPL loop. Whatever is typed here is forwarded to the game via CDP.
    #     Special local commands (starting with '/') are handled here and
    #     not forwarded to the game.
    # ES: Bucle REPL. Lo que se escriba aca se reenvia al juego via CDP.
    #     Los comandos locales (que empiezan con '/') se manejan aca y
    #     no se reenvian al juego.
    while True:
        try:
            msg = input("> ")
        except EOFError:
            break
        if not msg:
            continue

        # EN: Local command: /full -> disable truncation of decoded JSON.
        # ES: Comando local: /full -> desactiva el truncado del JSON decodificado.
        if msg.strip() in ("/full", "/full on"):
            empire_decoder.DECODED_PREVIEW_MAX = None
            print("[i] Full JSON mode ON / Modo JSON completo ACTIVADO")
            continue

        # EN: Local command: /full off -> restore truncation (400 chars).
        # ES: Comando local: /full off -> restaura el truncado (400 chars).
        if msg.strip() == "/full off":
            empire_decoder.DECODED_PREVIEW_MAX = 400
            print("[i] Full JSON mode OFF (400 chars) / Modo JSON completo DESACTIVADO")
            continue

        # EN: Local command: /full <n> -> custom truncation limit.
        # ES: Comando local: /full <n> -> limite de truncado custom.
        if msg.strip().startswith("/full "):
            parts = msg.strip().split()
            if len(parts) == 2:
                try:
                    empire_decoder.DECODED_PREVIEW_MAX = int(parts[1])
                    print(f"[i] Truncation limit set to {parts[1]} / Limite de truncado: {parts[1]}")
                    continue
                except ValueError:
                    pass
            print("[!] Usage / Uso: /full | /full on | /full off | /full <n>")
            continue

        relay = getattr(socket, "cdp_relay", None)
        if relay is None:
            print("[!] Relay not ready yet. Wait for 'CDP relay activo'.")
            print("[!] El relay todavia no esta listo. Espera a 'CDP relay activo'.")
            continue
        try:
            relay.send_to_game(msg)
            print(f"[SEND] {msg}")
        except Exception as e:
            print(f"[!] Error: {e}")