"""
EN: Entry point. Launches Chrome, connects the CDP relay, starts the HTTP
    bridge, and lets the user send raw Empire protocol commands from the
    terminal.
ES: Punto de entrada. Lanza Chrome, conecta el relay CDP, arranca el
    puente HTTP, y permite enviar comandos crudos del protocolo Empire
    desde la terminal.
"""

import os
import readline
import signal
import sys
import time

import lib.empire_decoder as empire_decoder
from lib.empire_decoder import RAW_LOG, DECODED_LOG, EVENTS_LOG
from lib.gge_socket_browser import GgeSocketBrowser
from lib.gge_browser_selenium import connect_with_browser
from lib.bridge_server import BridgeServer
from lib.colors import colors


def _rotate_logs():
    """
    EN: Rotate logs on startup: if a log exists and is larger than 50 MB,
        rename it with a timestamp suffix instead of appending forever.
    ES: Rotar logs al arrancar: si un log existe y pesa mas de 50 MB,
        renombrarlo con sufijo de timestamp en vez de appendear siempre.
    """
    # EN: Paths come from empire_decoder so there is a single source of
    #     truth. Rotation only renames the file; the old data is kept
    #     under the timestamped name.
    # ES: Los paths vienen del empire_decoder para tener una sola fuente
    #     de verdad. La rotacion solo renombra el archivo; los datos
    #     viejos quedan bajo el nombre con timestamp.
    for path in (RAW_LOG, DECODED_LOG, EVENTS_LOG):
        try:
            if os.path.exists(path) and os.path.getsize(path) > 50 * 1024 * 1024:
                rotated = f"{path}.{time.strftime('%Y%m%d_%H%M%S')}"
                os.rename(path, rotated)
                print(f"[i] Rotated {path} -> {rotated}", flush=True)
        except Exception as e:
            print(f"[!] rotate error on {path}: {e}", flush=True)


def _install_signal_handlers():
    """
    EN: Handle SIGTERM / SIGINT cleanly so the process exits even when it
        is not attached to a TTY (e.g. launched as a background job).
        Without this, Ctrl+C in a TTY works but a `kill <pid>` or a
        process supervisor's stop signal would be ignored, leaving
        Chrome orphaned.
    ES: Manejar SIGTERM / SIGINT para salir limpio aunque el proceso no
        este atado a una TTY (ej. lanzado como job en background). Sin
        esto, Ctrl+C en TTY anda pero un `kill <pid>` o la senal de stop
        de un supervisor seria ignorada, dejando Chrome huerfano.
    """
    def _handle(signum, _frame):
        name = signal.Signals(signum).name
        print(f"\n[PY] Received {name}, exiting... / Recibido {name}, saliendo...", flush=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)


def print_preserve_input(message):
    """
    EN: Print a message without losing the line currently being typed.
    ES: Imprime un mensaje sin perder la linea que se esta escribiendo.
    """
    input_buf = readline.get_line_buffer()
    sys.stdout.write(f"\x1b[2K\r{message}\n> {input_buf}")
    sys.stdout.flush()


def _run_repl(socket):
    """
    EN: Interactive REPL. Reads commands from stdin and forwards them to
        the game via CDP. Only runs when stdin is a TTY.
    ES: REPL interactivo. Lee comandos de stdin y los reenvia al juego
        via CDP. Solo corre cuando stdin es una TTY.
    """
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
            # EN: No print here. The SENT frame is shown as [SENT] [CMD] ...
            #     by the decoder once CDP captures it. Avoids a duplicate line.
            # ES: Sin print. El frame SENT aparece como [SENT] [CMD] ...
            #     cuando el CDP lo captura. Evita una linea duplicada.
        except Exception as e:
            print(f"[!] Error: {e}")


def _wait_for_signals():
    """
    EN: Block the main thread until a signal arrives. Used in background
        mode (stdin is not a TTY), where there is no REPL. The process
        stays alive serving the HTTP bridge until SIGTERM / SIGINT.
    ES: Bloquea el hilo principal hasta que llegue una senal. Se usa en
        modo background (stdin no es TTY), donde no hay REPL. El proceso
        queda vivo sirviendo el puente HTTP hasta SIGTERM / SIGINT.
    """
    print(
        "[PY] stdin is not a TTY: running in background mode. "
        "Send SIGTERM or SIGINT to stop.",
        flush=True,
    )
    print(
        "[PY] stdin no es TTY: modo background. Enviar SIGTERM o SIGINT "
        "para detener.",
        flush=True,
    )
    # EN: signal.pause() blocks until any signal is delivered. Our
    #     SIGTERM/SIGINT handlers call sys.exit(0), so this returns
    #     cleanly.
    # ES: signal.pause() bloquea hasta que llegue cualquier senal.
    #     Nuestros handlers de SIGTERM/SIGINT llaman a sys.exit(0), asi
    #     que esto retorna limpio.
    while True:
        signal.pause()


if __name__ == '__main__':
    # EN: Rotate oversized logs before importing anything that opens them.
    #     empire_decoder now uses lazy-open (init_logs), so no file handle
    #     exists until the first write. Rotation is effective.
    # ES: Rotar logs gigantes antes de importar nada que los abra.
    #     empire_decoder ahora usa apertura perezosa (init_logs), asi que
    #     no existe ningun handle hasta la primera escritura. La rotacion
    #     es efectiva.
    _rotate_logs()

    # EN: Install SIGTERM / SIGINT handlers so the process can be stopped
    #     cleanly from outside a TTY.
    # ES: Instalar handlers de SIGTERM / SIGINT para poder frenar el
    #     proceso limpiamente desde fuera de una TTY.
    _install_signal_handlers()

    # EN: Callback container. In the CDP relay architecture this object
    #     does not open a real WebSocket; it only holds callbacks.
    #     on_send and on_message are intentionally None: the decoder in
    #     gge_browser_selenium already prints every frame (raw is also
    #     written to RAW_LOG / DECODED_LOG). Setting them here would
    #     duplicate every line on the terminal.
    # ES: Contenedor de callbacks. En la arquitectura de relay CDP este
    #     objeto no abre un WebSocket real; solo guarda callbacks.
    #     on_send y on_message quedan en None a proposito: el decoder en
    #     gge_browser_selenium ya imprime cada frame (y ademas el crudo
    #     va a RAW_LOG / DECODED_LOG). Setearlos aca duplicaria cada
    #     linea en la terminal.
    socket = GgeSocketBrowser(
        on_send=None,
        on_open=lambda ws: print_preserve_input(colors.LIGHT_MAGENTA + 'WebSocket opened' + colors.ENDC),
        on_message=None,
        on_error=lambda ws, error: print_preserve_input(colors.LIGHT_RED + f"Error in websocket: {error}" + colors.ENDC),
        on_close=lambda ws, close_status_code, close_msg: print_preserve_input(colors.LIGHT_MAGENTA + f'WebSocket closed with code {close_status_code} and message {close_msg}' + colors.ENDC),
    )

    # EN: Start the HTTP bridge. It picks up the relay once Chrome is
    #     connected (the socket exposes .cdp_relay dynamically), so it is
    #     safe to start before connect_with_browser().
    # ES: Arrancar el puente HTTP. Toma el relay una vez que Chrome este
    #     conectado (el socket expone .cdp_relay dinamicamente), asi que
    #     es seguro arrancarlo antes de connect_with_browser().
    bridge = BridgeServer(socket, host="0.0.0.0", port=4444, timeout=15.0)
    empire_decoder.set_response_callback(bridge.handle_response)
    bridge.start()
    print(
        "[PY] Bridge HTTP listening on / Escuchando en http://0.0.0.0:4444",
        flush=True,
    )

    # EN: Launch Chrome and start the CDP relay.
    #     To target a non-GGS host, pass game_domain="your.host.com".
    # ES: Lanza Chrome y arranca el relay CDP.
    #     Para apuntar a un host que no sea GGS, pasar game_domain="tu.host".
    connect_with_browser(
        socket,
        'https://danadum.github.io/empire',
        8765,
        # game_domain="empire-html5.goodgamestudios.com",
    )

    # EN: If stdin is a TTY, run the interactive REPL. Otherwise (nohup,
    #     systemd, background job) just wait for a signal. This is what
    #     makes GGE_DETACH=0 + nohup work without crashing on input().
    # ES: Si stdin es TTY, correr el REPL interactivo. Si no (nohup,
    #     systemd, job en background) solo esperar una senal. Esto es lo
    #     que hace que GGE_DETACH=0 + nohup funcione sin crashear en
    #     input().
    if sys.stdin.isatty():
        _run_repl(socket)
    else:
        _wait_for_signals()