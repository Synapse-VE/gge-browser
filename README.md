# gge-browser

EN: Python library to open the game [Goodgame Empire](https://empire.goodgamestudios.com) in a browser with control over the game socket from the code.

ES: Libreria en Python para abrir el juego [Goodgame Empire](https://empire.goodgamestudios.com) en un navegador con control sobre el socket del juego desde el codigo.

---

## Status / Estado

EN: The original WebSocket proxy approach is broken on Chrome 145+. Chrome now blocks Private Network Access (PNA) between public HTTPS pages and `localhost`, uses Out-Of-Process IFrames (OOPIF), and rejects Python TLS fingerprints at the server WAF. This fork replaces the proxy with a **CDP relay** architecture:

- Chrome talks to Goodgame servers directly (native WebSocket).
- Python listens to WebSocket frames via Chrome DevTools Protocol (`Network.webSocketFrameReceived` / `Network.webSocketFrameSent`).
- Python injects commands via `Runtime.evaluate` on a passive hook installed over `WebSocket.prototype.send`.

This avoids binary corruption and TLS fingerprint detection.

ES: El metodo original de proxy WebSocket esta roto en Chrome 145+. Chrome ahora bloquea Private Network Access (PNA) entre paginas HTTPS publicas y `localhost`, usa iframes en procesos separados (OOPIF), y rechaza fingerprints TLS de Python en el WAF del servidor. Este fork reemplaza el proxy por una arquitectura de **relay CDP**:

- Chrome habla directo con los servidores de Goodgame (WebSocket nativo).
- Python escucha los frames WebSocket via Chrome DevTools Protocol (`Network.webSocketFrameReceived` / `Network.webSocketFrameSent`).
- Python inyecta comandos via `Runtime.evaluate` sobre un hook pasivo instalado en `WebSocket.prototype.send`.

Esto evita corrupcion binaria y deteccion por fingerprint TLS.

---

## Requirements / Requisitos

- **Google Chrome 145+** (tested on 155.0.8059.39)
- **Python 3.11+** (tested on 3.14)
- Linux, macOS, or Windows (see [Platform notes](#platform-notes--notas-de-plataforma) for Windows caveats)

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
[CDP] Connection open, enabling Network + Runtime
[CDP] Conexion abierta, habilitando Network + Runtime
[CDP] Runtime.evaluate id=2 -> HOOK_INSTALLED
[CDP] Game WebSocket created / WebSocket del juego creado: requestId=110298.144
[PY] CDP relay active. / CDP relay activo.
[PY] Raw log / Log crudo: /tmp/gge_raw.log
[PY] Decoded log / Log decodificado: /tmp/gge_decoded.log
> [RECV] [CMD] ServerInfoInit (status=1) {}
[RECV] [CMD] GetResourcesCastle (status=1) {"W":795021.25,"S":795007.0,...}
[SENT] [CMD] Ping (status=1) <RoundHouseKick>
>
```

### REPL commands / Comandos del REPL

EN: In addition to raw protocol commands, the REPL accepts a few local commands that are handled before anything is sent to the game:

ES: Ademas de comandos crudos del protocolo, el REPL acepta algunos comandos locales que se manejan antes de enviar nada al juego:

| Command | Effect (EN) | Efecto (ES) |
|---|---|---|
| `/full` or `/full on` | Disable JSON truncation. Full payload printed. | Desactiva el truncado. Se imprime el JSON completo. |
| `/full off` | Restore 400-character preview. | Restaura el preview de 400 caracteres. |
| `/full <n>` | Custom character limit. Example: `/full 2000`. | Limite de caracteres custom. Ejemplo: `/full 2000`. |

EN: You can also set the initial mode via environment variable:

ES: Tambien podes fijar el modo inicial via variable de entorno:

```sh
GGE_DECODED_FULL=1 python -u main.py    # full JSON from startup
GGE_DECODED_MAX=2000 python -u main.py  # custom initial limit
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
|  lib/empire_decoder.py-> base64 decoder + human formatter   |
|  lib/gge_browser_selenium.py -> launches Chrome, wires up   |
+-------------------------------------------------------------+
```

EN: Python never opens its own WebSocket to Goodgame. It only observes and injects frames on Chrome's native socket.

ES: Python nunca abre su propio WebSocket a Goodgame. Solo observa e inyecta frames en el socket nativo de Chrome.

EN: **How injection works:** the game hides its WebSocket inside a module closure, so `window.socket` is `undefined`. When `Runtime.enable` is issued, the relay installs a passive hook on `WebSocket.prototype.send`. The next time the game sends any frame (for example the periodic `pin`), the hook registers the instance in `window.__gge_ws_list`. From that point on, `send_to_game()` picks the socket whose URL contains `goodgamestudios` and calls `.send(payload)` on it. No polling, no `queryObjects`, no cross-origin issues.

ES: **Como funciona la inyeccion:** el juego esconde su WebSocket dentro de un closure de modulo, asi que `window.socket` es `undefined`. Cuando se emite `Runtime.enable`, el relay instala un hook pasivo en `WebSocket.prototype.send`. La proxima vez que el juego envia cualquier frame (por ejemplo el `pin` periodico), el hook registra la instancia en `window.__gge_ws_list`. Desde ahi, `send_to_game()` elige el socket cuya URL contiene `goodgamestudios` y llama `.send(payload)` sobre el. Sin polling, sin `queryObjects`, sin problemas de cross-origin.

---

## Sending commands / Enviando comandos

EN: At the `>` prompt, type any raw Empire protocol command. It is sent to the game via `Runtime.evaluate` calling `.send()` on the captured game socket (see Architecture above). Example:

ES: En el prompt `>`, escribe cualquier comando crudo del protocolo Empire. Se envia al juego via `Runtime.evaluate` llamando `.send()` sobre el socket capturado del juego (ver Arquitectura arriba). Ejemplo:

```text
> %xt%EmpireEx_25%hgh%1%{"LT":13,"LID":-1,"SV":"-1"}%
[SEND] %xt%EmpireEx_25%hgh%1%{"LT":13,"LID":-1,"SV":"-1"}%
[CDP] Runtime.evaluate id=5 -> OK i=0 list=1 url=wss://ep-live-his1-game.goodgamestudios.com/
[SENT] [CMD] hgh (dict keys=['LT', 'LID', 'SV'])
[RECV] [CMD] Highscore (dict keys=['HL', 'HN', 'LID'])
```

EN: Every frame received from the server is printed as `[RECV] [CMD] <CommandName> (status=<n>) <payload>`. Every frame sent by the client (either you or the game itself) is printed as `[SENT] [CMD] ...`. The raw untouched payloads are written to `/tmp/gge_raw.log` for offline analysis.

ES: Cada frame recibido del servidor se imprime como `[RECV] [CMD] <NombreComando> (status=<n>) <payload>`. Cada frame enviado por el cliente (sea vos o el juego mismo) se imprime como `[SENT] [CMD] ...`. Los payloads crudos sin tocar se escriben a `/tmp/gge_raw.log` para analisis offline.

EN: The base64-wrapped EmpireEx variant (frames starting with `JXh0`, which is `%xt` encoded) is decoded automatically. The terminal shows a preview of the decoded JSON; the full decoded text is written to `/tmp/gge_decoded.log`.

ES: La variante EmpireEx envuelta en base64 (frames que empiezan con `JXh0`, que es `%xt` codificado) se decodifica automaticamente. La terminal muestra un preview del JSON decodificado; el texto completo decodificado se escribe a `/tmp/gge_decoded.log`.

---

## Decoded logs / Logs decodificados

EN: Two log files are produced per session:

ES: Se producen dos archivos de log por sesion:

| File | Contents (EN) | Contenido (ES) |
|---|---|---|
| `/tmp/gge_raw.log` | Every frame exactly as it crossed the wire, base64 included. | Cada frame tal cual cruzo el cable, base64 incluido. |
| `/tmp/gge_decoded.log` | Every base64 blob expanded to its decoded text. Never truncated. | Cada blob base64 expandido a texto. Nunca truncado. |

EN: Use `gge_decoded.log` for offline parsing. It is a plain text file with one frame per section, separated by `=== <direction> (<n> bytes) ===` headers.

ES: Usa `gge_decoded.log` para parsear offline. Es un archivo de texto plano con un frame por seccion, separados por headers `=== <direction> (<n> bytes) ===`.

---

## Files / Archivos

| File | Purpose (EN) | Proposito (ES) |
|---|---|---|
| `main.py` | Entry point and REPL loop | Punto de entrada y bucle REPL |
| `lib/cdp_relay.py` | Chrome DevTools Protocol client | Cliente del Chrome DevTools Protocol |
| `lib/empire_decoder.py` | EmpireEx base64 decoder and formatter | Decodificador base64 y formateador EmpireEx |
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

**EN: Commands typed at `>` produce no `[SENT]` and no `[RECV]`**

The passive WebSocket hook has not captured the game socket yet. This is normal for the first ~30 seconds after connecting: the hook only fires when the game sends its next frame (usually the periodic `pin`). Solutions:

- Wait 30 seconds and try again.
- Or reload the game tab (`F5`). The relay will reinstall the hook and the game will immediately send a fresh frame.

You can verify the capture worked by looking for:

```text
[CDP] Runtime.evaluate id=X -> OK i=0 list=1 url=wss://...goodgamestudios.com/
```

If instead you see `NO_WS_YET list=0 []`, the hook has not captured anything yet.

**ES: Los comandos en `>` no producen `[SENT]` ni `[RECV]`**

El hook pasivo del WebSocket todavia no capturo el socket del juego. Esto es normal durante los primeros ~30 segundos tras conectar: el hook solo se dispara cuando el juego envia su proximo frame (usualmente el `pin` periodico). Soluciones:

- Espera 30 segundos e intenta de nuevo.
- O recarga la pestaña del juego (`F5`). El relay reinstalara el hook y el juego enviara un frame fresco inmediatamente.

Podes verificar que la captura funciono buscando:

```text
[CDP] Runtime.evaluate id=X -> OK i=0 list=1 url=wss://...goodgamestudios.com/
```

Si en cambio ves `NO_WS_YET list=0 []`, el hook todavia no capturo nada.

---

## Platform notes / Notas de plataforma

EN: The current code was developed and tested on Linux. macOS works out of the box. Windows works but needs two small adjustments:

**1. Hardcoded `/tmp/` paths.** `lib/empire_decoder.py` writes to `/tmp/gge_raw.log` and `/tmp/gge_decoded.log`. On Windows `/tmp/` does not exist. Either create `C:\tmp\` manually, or patch the constants at the top of the file:

```python
import tempfile
_TMP = tempfile.gettempdir()
RAW_LOG = _TMP + "/gge_raw.log"
DECODED_LOG = _TMP + "/gge_decoded.log"
```

**2. `readline` module.** `main.py` imports `readline` at the top. Python's standard library does not ship `readline` on Windows. Install the drop-in replacement:

```sh
pip install pyreadline3
```

`pyreadline3` registers itself under the `readline` name, so `import readline` keeps working unchanged.

**3. Troubleshooting commands.** The `pkill -9 -f chrome` and `rm -rf user-data/` snippets in the Troubleshooting section are Unix-only. Windows equivalents:

```powershell
taskkill /F /IM chrome.exe
rmdir /S /Q user-data
```

ES: El codigo actual fue desarrollado y probado en Linux. macOS funciona sin cambios. Windows funciona pero necesita dos ajustes chicos:

**1. Rutas `/tmp/` hardcodeadas.** `lib/empire_decoder.py` escribe a `/tmp/gge_raw.log` y `/tmp/gge_decoded.log`. En Windows `/tmp/` no existe. O creas `C:\tmp\` a mano, o parcheas las constantes al inicio del archivo (mismo snippet de arriba).

**2. Modulo `readline`.** `main.py` importa `readline` al inicio. La libreria estandar de Python no incluye `readline` en Windows. Instala el reemplazo directo:

```sh
pip install pyreadline3
```

`pyreadline3` se registra bajo el nombre `readline`, asi que `import readline` sigue funcionando sin cambios.

**3. Comandos de troubleshooting.** Los snippets `pkill -9 -f chrome` y `rm -rf user-data/` de la seccion Troubleshooting son solo-Unix. Equivalentes en Windows:

```powershell
taskkill /F /IM chrome.exe
rmdir /S /Q user-data
```

EN: **Linux-only features:** none. The hook mechanism, CDP relay, decoder and REPL all work identically on every platform once the two adjustments above are applied.

ES: **Funciones solo-Linux:** ninguna. El mecanismo del hook, el relay CDP, el decoder y el REPL funcionan igual en cualquier plataforma una vez aplicados los dos ajustes de arriba.

---

## Security / Seguridad

EN: This fork does not use `--disable-web-security`. Chrome talks to Goodgame with its own TLS stack and normal security policies. The `user-data/` directory is a separate Chrome profile used only by this tool; do not use it for regular browsing.

ES: Este fork no usa `--disable-web-security`. Chrome habla con Goodgame con su propio stack TLS y politicas de seguridad normales. El directorio `user-data/` es un perfil de Chrome separado usado solo por esta herramienta; no lo uses para navegar normalmente.

**EN: Never commit `user-data/`.** It contains session cookies for your Goodgame account.

**ES: Nunca hagas commit de `user-data/`.** Contiene cookies de sesion de tu cuenta de Goodgame.

**EN: Terms of Service.** Goodgame Studios' ToS prohibit automation, bots, and external tools that interact with the game. This project is provided for educational and interoperability research purposes only. Using it on a live account may result in warnings, temporary suspension or a permanent ban. You assume all risk.

**ES: Terminos de Servicio.** Los ToS de Goodgame Studios prohiben la automatizacion, los bots y las herramientas externas que interactuen con el juego. Este proyecto se provee solo con fines educativos y de investigacion de interoperabilidad. Usarlo en una cuenta activa puede resultar en advertencias, suspension temporal o ban permanente. Asumis todo el riesgo.

---

## Credits / Creditos

EN: Original project by [danadum](https://github.com/danadum). Chrome 155+ compatibility (CDP relay), EmpireEx decoder and passive WebSocket hook added by [Synapse-VE](https://github.com/Synapse-VE).

ES: Proyecto original de [danadum](https://github.com/danadum). Compatibilidad con Chrome 155+ (relay CDP), decoder EmpireEx y hook pasivo del WebSocket agregados por [Synapse-VE](https://github.com/Synapse-VE).

---

## License / Licencia

EN: Same license as the original project.

ES: Misma licencia que el proyecto original.