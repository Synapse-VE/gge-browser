"""
EN: EmpireEx protocol decoder. Handles the raw EmpireEx text frames
    used by Goodgame Empire, including the base64-wrapped variant
    (starts with 'JXh0' == base64('%xt')). Writes both the raw payload
    and the decoded text to separate log files.
ES: Decodificador del protocolo EmpireEx. Maneja los frames de texto
    EmpireEx usados por Goodgame Empire, incluida la variante envuelta
    en base64 (empieza con 'JXh0' == base64('%xt')). Escribe tanto el
    payload crudo como el texto decodificado a archivos de log separados.
"""

import base64
import json
import os
import re

# EN: Raw log file for auditing every frame without truncation.
# ES: Archivo de log crudo para auditar todos los frames sin truncar.
RAW_LOG = "/tmp/gge_raw.log"
# EN: Decoded log: same frames but with base64 blobs expanded to text.
# ES: Log decodificado: los mismos frames pero con los blobs base64
#     expandidos a texto.
DECODED_LOG = "/tmp/gge_decoded.log"

# EN: Max characters of the decoded payload to show on the terminal.
#     Set GGE_DECODED_FULL=1 to disable truncation entirely.
#     Set GGE_DECODED_MAX=<n> to use a custom character limit.
# ES: Maximo de caracteres del payload decodificado a mostrar en terminal.
#     Poner GGE_DECODED_FULL=1 desactiva el truncado por completo.
#     Poner GGE_DECODED_MAX=<n> usa un limite de caracteres custom.
if os.environ.get("GGE_DECODED_FULL", "").strip().lower() in ("1", "true", "yes", "on"):
    # EN: No truncation. / ES: Sin truncado.
    DECODED_PREVIEW_MAX = None
else:
    try:
        DECODED_PREVIEW_MAX = int(os.environ.get("GGE_DECODED_MAX", "400"))
    except ValueError:
        DECODED_PREVIEW_MAX = 400

# EN: Friendly names for common EmpireEx commands.
# ES: Nombres legibles para comandos EmpireEx comunes.
FRIENDLY_CMD = {
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
    "gam": "GameMessage",
}

_raw_fp = open(RAW_LOG, "a", buffering=1)
_decoded_fp = open(DECODED_LOG, "a", buffering=1)


def _decode_b64_empire(payload):
    """
    EN: Decode a base64 payload if it looks like an EmpireEx frame
        (starts with 'JXh0' == base64('%xt')). Returns decoded text or
        None if it is not a base64 EmpireEx blob.
    ES: Decodifica un payload base64 si parece un frame EmpireEx
        (empieza con 'JXh0' == base64('%xt')). Devuelve el texto
        decodificado o None si no es un blob EmpireEx en base64.
    """
    if not payload.startswith("JXh0"):
        return None
    try:
        raw = base64.b64decode(payload)
    except Exception as e:
        return f"<b64 decode error: {e}>"
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _extract_json(decoded):
    """
    EN: Extract the JSON body from a decoded EmpireEx frame. Robust
        against '%' characters appearing inside the JSON. Returns
        (json_str, prefix) or (None, None).
    ES: Extrae el cuerpo JSON de un frame EmpireEx decodificado.
        Robusto ante caracteres '%' dentro del JSON. Devuelve
        (json_str, prefix) o (None, None).
    """
    start = -1
    for i, c in enumerate(decoded):
        if c in "{[":
            start = i
            break
    if start < 0:
        return None, None
    for i in range(len(decoded) - 1, start, -1):
        if decoded[i] in "}]":
            return decoded[start:i + 1], decoded[:start]
    return None, None


def _find_command(prefix):
    """
    EN: Find the EmpireEx command code inside the frame prefix, e.g.
        '%xt%all%1%0%' -> 'all'; '%xt%EmpireEx_25%hgh%1%' -> 'hgh'.
    ES: Encuentra el codigo de comando EmpireEx dentro del prefijo,
        ej. '%xt%all%1%0%' -> 'all'; '%xt%EmpireEx_25%hgh%1%' -> 'hgh'.
    """
    if not prefix:
        return None
    parts = prefix.strip("%").split("%")
    for p in parts:
        if p == "xt":
            continue
        if p in FRIENDLY_CMD:
            return p
    for p in parts:
        if p != "xt" and re.fullmatch(r"[a-z]{2,4}", p):
            return p
    return None


def _summarize_json(obj):
    """
    EN: One-line compact description of a decoded JSON body.
    ES: Descripcion compacta de una linea de un cuerpo JSON decodificado.
    """
    if isinstance(obj, dict):
        keys = list(obj.keys())
        shown = keys[:10]
        extra = f" (+{len(keys) - 10} more)" if len(keys) > 10 else ""
        return f"dict keys={shown}{extra}"
    if isinstance(obj, list):
        out = f"list len={len(obj)}"
        if obj and isinstance(obj[0], dict):
            out += f" first_keys={list(obj[0].keys())[:8]}"
        return out
    return f"{type(obj).__name__}={str(obj)[:80]}"


def _format_empire_text(decoded, direction):
    """
    EN: Build a human-readable line for a decoded EmpireEx text frame.
    ES: Construye una linea legible para un frame EmpireEx ya decodificado.
    """
    if not decoded.startswith("%xt%"):
        # EN: Full output mode: no truncation.
        # ES: Modo salida completa: sin truncado.
        if DECODED_PREVIEW_MAX is None:
            return f"[{direction}] [TXT] {decoded}"
        preview = decoded[:DECODED_PREVIEW_MAX]
        suffix = "..." if len(decoded) > DECODED_PREVIEW_MAX else ""
        return f"[{direction}] [TXT] {preview}{suffix}"

    json_str, prefix = _extract_json(decoded)
    cmd = _find_command(prefix)
    friendly = FRIENDLY_CMD.get(cmd, cmd or "?")

    if not json_str:
        return f"[{direction}] [CMD] {friendly}"

    try:
        obj = json.loads(json_str)
    except Exception:
        if DECODED_PREVIEW_MAX is None:
            return f"[{direction}] [CMD] {friendly} (raw) {json_str}"
        preview = json_str[:DECODED_PREVIEW_MAX]
        suffix = "..." if len(json_str) > DECODED_PREVIEW_MAX else ""
        return f"[{direction}] [CMD] {friendly} (raw) {preview}{suffix}"

    summary = _summarize_json(obj)
    try:
        pretty = json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception:
        pretty = json_str
    # EN: Full output mode: no truncation.
    # ES: Modo salida completa: sin truncado.
    if DECODED_PREVIEW_MAX is None:
        return f"[{direction}] [CMD] {friendly} ({summary})\n{pretty}"
    preview = pretty[:DECODED_PREVIEW_MAX]
    suffix = "\n..." if len(pretty) > DECODED_PREVIEW_MAX else ""
    return f"[{direction}] [CMD] {friendly} ({summary})\n{preview}{suffix}"


def format_payload(payload, direction):
    """
    EN: Convert a raw WebSocket frame into a human-readable line.
    ES: Convierte un frame WebSocket crudo en una linea legible.
    direction: "RECV" (from server) or "SENT" (from client).
    """
    # EN: Always write the raw frame to file first.
    # ES: Siempre escribimos el frame crudo al archivo primero.
    _raw_fp.write(f"\n=== {direction} ({len(payload)} bytes) ===\n{payload}\n")

    # EN: Base64-encoded EmpireEx blob -> decode and format.
    # ES: Blob EmpireEx en base64 -> decodificar y formatear.
    decoded = _decode_b64_empire(payload)
    if decoded is not None:
        _decoded_fp.write(
            f"\n=== {direction} ({len(payload)} b64 -> {len(decoded)} txt) ===\n"
            f"{decoded}\n"
        )
        inner = _format_empire_text(decoded, direction)
        return f"[{direction}] [BIN->TXT] ({len(payload)} b64) {inner}"

    # EN: SmartFox XML message.
    # ES: Mensaje XML de SmartFox.
    if payload.startswith("<"):
        m = re.match(
            r"<msg t='(.*?)'><body action='(.*?)' r='(.*?)'>(.*?)</body></msg>",
            payload,
        )
        if m:
            t, action, r, data = m.groups()
            return f"[{direction}] [XML] t={t} action={action} r={r} data={data[:120]}"
        return f"[{direction}] [XML] {payload[:120]}"

    # EN: Plain EmpireEx text frame (no base64).
    # ES: Frame EmpireEx de texto plano (sin base64).
    if payload.startswith("%xt%"):
        return _format_empire_text(payload, direction)

    # EN: Unknown format.
    # ES: Formato desconocido.
    return f"[{direction}] [???] {payload[:120]}"