# gge-browser

EN: Python library to open the game [Goodgame Empire](https://empire.goodgamestudios.com) in a browser with control over the game socket from the code.

ES: Libreria en Python para abrir el juego [Goodgame Empire](https://empire.goodgamestudios.com) en un navegador con control sobre el socket del juego desde el codigo.

---

## Status / Estado

EN: The original WebSocket proxy approach is broken on Chrome 145+. Chrome now blocks Private Network Access (PNA) between public HTTPS pages and `localhost`, uses Out-Of-Process IFrames (OOPIF), and rejects Python TLS fingerprints at the server WAF. This fork replaces the proxy with a **CDP relay** architecture:

- Chrome talks to Goodgame servers directly (native WebSocket).
- Python listens to WebSocket frames via Chrome DevTools Protocol (`Network.webSocketFrameReceived` / `Network.webSocketFrameSent`).
- Python injects commands via `Runtime.evaluate`.

This avoids binary corruption and TLS fingerprint detection.

ES: El metodo original de proxy WebSocket esta roto en Chrome 145+. Chrome ahora bloquea Private Network Access (PNA) entre paginas HTTPS publicas y `localhost`, usa iframes en procesos separados (OOPIF), y rechaza fingerprints TLS de Python en el WAF del servidor. Este fork reemplaza el proxy por una arquitectura de **relay CDP**:

- Chrome habla directo con los servidores de Goodgame (WebSocket nativo).
- Python escucha los frames WebSocket via Chrome DevTools Protocol (`Network.webSocketFrameReceived` / `Network.webSocketFrameSent`).
- Python inyecta comandos via `Runtime.evaluate`.

Esto evita corrupcion binaria y deteccion por fingerprint TLS.

---

## Requirements / Requisitos

- **Google Chrome 145+** (tested on 155.0.8059.39)
- **Python 3.11+** (tested on 3.14)
- Linux, macOS, or Windows

Dependencies:

- `selenium >= 4.20`
- `websocket-client`
- `requests`
- `pygge` (from `requirements.txt`)
- `websockets`

---

## Installation / Instalacion

EN: Clone the repository, create a virtual environment, and install the required dependencies.

ES: Clona el repositorio, crea un entorno virtual, e instala las dependencias requeridas.

```sh
git clone https://github.com/YOUR_USER/gge-browser.git
cd gge-browser

python -m venv .venv
source .venv/bin/activate     # Linux / macOS
# .venv\Scripts\activate      # Windows

pip install --upgrade pip
pip install -r requirements.txt
```

EN: Make sure `google-chrome` is available on your PATH.

ES: Asegurate de que `google-chrome` este disponible en el PATH.

```sh
which google-chrome
google-chrome --version
```

EN: On Arch / EndeavourOS you may need to install it manually from the AUR:

ES: En Arch / EndeavourOS puede que necesites instalarlo manualmente desde AUR:

```sh
yay -S google-chrome
```

---

## Usage / Uso

EN: Run the entry point:

ES: Ejecuta el punto de entrada:

```sh
python -u main.py
```

EN: Chrome will open automatically, navigate to the wrapper page, and load the game inside an iframe. Once the game reaches its login screen:

1. Log in with your Goodgame account.
2. Wait until the terminal shows `CDP relay active.`
3. Type raw protocol commands at the `>` prompt.

ES: Chrome se abrira automaticamente, navegara a la pagina del wrapper, y cargara el juego dentro de un iframe. Una vez que el juego llegue a la pantalla de login:

1. Inicia sesion con tu cuenta de Goodgame.
2. Espera a que la terminal muestre `CDP relay active.`
3. Escribe comandos crudos del protocolo en el prompt `>`.

EN: Example session output:

ES: Ejemplo de salida de sesion:

```text
[PY] Launching Chrome... / Lanzando Chrome...
[PY] Chrome: 155.0.8059.39
[PY] Navigated to / Navegando a: https://danadum.github.io/empire/?nomobileredirect=true
[PY] Waiting for iframe#game... / Esperando iframe#game...
[PY] iframe found, connecting CDP relay / iframe encontrado, conectando relay CDP
[CDP] Connection open, enabling Network domain
[CDP] Conexion abierta, habilitando dominio Network
[PY] CDP relay active. / CDP relay activo.
[PY] Raw log / Log crudo: /tmp/gge_raw.log
> [RECV] [CMD] ServerInfoInit (status=1) {}
[RECV] [CMD] GetResourcesCastle (status=1) {"W":795021.25,"S":795007.0,...}
[SENT] [CMD] Ping (status=1) <RoundHouseKick>
>
```

---

## Architecture / Arquitectura

```text
+--------------+        native WSS         +------------------+
|   Chrome     | <-----------------------> |  Goodgame server |
|  (iframe)    |                           +------------------+
|              |
|  game WS     | <---- CDP listen/inject --+
+--------------+                           |
                                           |
+------------------------------------------+------------------+
|  Python process                                             |
|                                                             |
|  main.py              -> REPL loop                          |
|  lib/cdp_relay.py     -> CDP client (frames in / cmds out)  |
|  lib/gge_browser_selenium.py -> launches Chrome, wires up   |
+-------------------------------------------------------------+
```

EN: Python never opens its own WebSocket to Goodgame. It only observes and injects frames on Chrome's native socket.

ES: Python nunca abre su propio WebSocket a Goodgame. Solo observa e inyecta frames en el socket nativo de Chrome.

---

## Sending commands / Enviando comandos

EN: At the `>` prompt, type any raw Empire protocol command. It is sent to the game through `window.socket.send(...)`. Example:

ES: En el prompt `>`, escribe cualquier comando crudo del protocolo Empire. Se envia al juego a traves de `window.socket.send(...)`. Ejemplo:

```text
> %xt%EmpireEx_25%hgh%1%{"LT":13,"LID":-1,"SV":"-1"}%
[SEND] %xt%EmpireEx_25%hgh%1%{"LT":13,"LID":-1,"SV":"-1"}%
```

EN: Every frame received from the server is printed as `[RECV] [CMD] <CommandName> (status=<n>) <payload>`. Every frame sent by the client is printed as `[SENT] [CMD] ...`. The raw untouched payloads are written to `/tmp/gge_raw.log` for offline analysis.

ES: Cada frame recibido del servidor se imprime como `[RECV] [CMD] <NombreComando> (status=<n>) <payload>`. Cada frame enviado por el cliente se imprime como `[SENT] [CMD] ...`. Los payloads crudos sin tocar se escriben a `/tmp/gge_raw.log` para analisis offline.

---

## Files / Archivos

| File | Purpose (EN) | Proposito (ES) |
|---|---|---|
| `main.py` | Entry point and REPL loop | Punto de entrada y bucle REPL |
| `lib/cdp_relay.py` | Chrome DevTools Protocol client | Cliente del Chrome DevTools Protocol |
| `lib/gge_browser_selenium.py` | Launches Chrome, wires the relay | Lanza Chrome y conecta el relay |
| `lib/gge_socket_browser.py` | Legacy callback container | Contenedor de callbacks legado |
| `lib/websocket_server.py` | Legacy WS proxy (unused) | Proxy WS legado (no usado) |
| `lib/colors.py` | ANSI color codes | Codigos ANSI de color |

---

## Troubleshooting / Solucion de problemas

**EN: `google-chrome not found`**

Install Google Chrome. On Arch-based distros, use the AUR:

**ES: `google-chrome not found`**

Instala Google Chrome. En distros basadas en Arch, usa el AUR:

```sh
yay -S google-chrome
```

---

**EN: `Handshake status 403 Forbidden` when connecting to CDP**

Chrome 111+ requires the `--remote-allow-origins=*` flag AND `suppress_origin=True` on the client. Both are already set in this fork.

**ES: `Handshake status 403 Forbidden` al conectar al CDP**

Chrome 111+ requiere la flag `--remote-allow-origins=*` Y `suppress_origin=True` en el cliente. Ambas ya estan configuradas en este fork.

---

**EN: `unable to discover open window in chrome`**

Chrome left a locked `user-data/` directory behind. Clean up:

**ES: `unable to discover open window in chrome`**

Chrome dejo un directorio `user-data/` bloqueado. Limpia:

```sh
pkill -9 -f chrome
rm -rf user-data/
```

---

**EN: Game stuck at "Sharpening swords" / login screen never loads**

The relay did not connect. Check `/tmp/gge_raw.log` and the DevTools console of the `index.html` iframe. You should see `[GGE] new WebSocket` logs.

**ES: Juego atascado en "Afilando las espadas" / login nunca carga**

El relay no conecto. Revisa `/tmp/gge_raw.log` y la consola de DevTools del iframe `index.html`. Deberias ver logs `[GGE] new WebSocket`.

---

## Security / Seguridad

EN: This fork does not use `--disable-web-security`. Chrome talks to Goodgame with its own TLS stack and normal security policies. The `user-data/` directory is a separate Chrome profile used only by this tool; do not use it for regular browsing.

ES: Este fork no usa `--disable-web-security`. Chrome habla con Goodgame con su propio stack TLS y politicas de seguridad normales. El directorio `user-data/` es un perfil de Chrome separado usado solo por esta herramienta; no lo uses para navegar normalmente.

**EN: Never commit `user-data/`.** It contains session cookies for your Goodgame account.

**ES: Nunca hagas commit de `user-data/`.** Contiene cookies de sesion de tu cuenta de Goodgame.

---

## Credits / Creditos

EN: Original project by [danadum](https://github.com/danadum). Chrome 155+ compatibility (CDP relay) added by [Synapse-VE](https://github.com/Synapse-VE).

ES: Proyecto original de [danadum](https://github.com/danadum). Compatibilidad con Chrome 155+ (relay CDP) agregada por [Synapse-VE](https://github.com/Synapse-VE).

---

## License / Licencia

EN: Same license as the original project.

ES: Misma licencia que el proyecto original.
