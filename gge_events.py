#!/usr/bin/env python3
"""
EN: Read-only `sei` (events) fetch for the live GGE Chrome session.
    It installs a passive WebSocket hook through CDP, waits for the game
    socket (the hook captures it on the next game send), sends `sei` and
    parses the response. If the live socket is not available, it falls back
    to the last `sei` frame in the session log.

ES: Lectura de eventos (`sei`) sobre la sesion real de Chrome de GGE.
    Instala un hook pasivo del WebSocket por CDP, espera el socket del
    juego (el hook lo captura en el proximo envio), manda `sei` y parsea
    la respuesta. Si el socket no esta disponible, cae al ultimo frame
    `sei` del log de la sesion.
"""

import base64
import json
import os
import re
import sys
import time

import requests
import websocket

DEFAULT_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".gge-session.log")
ZONE_RE = re.compile(r"xt%(EmpireEx_\d+)%")

HOOK_JS = r"""
(function () {
  if (window.__gge_events_cap) {
    return 'ALREADY ws=' + (window.__gge_events_cap.ws ? '1' : '0');
  }
  window.__gge_events_cap = {frames: [], ws: null};

  function push(t) {
    try {
      var s = String(t);
      window.__gge_events_cap.frames.push(s.slice(0, 120000));
      if (window.__gge_events_cap.frames.length > 80) window.__gge_events_cap.frames.shift();
    } catch (e) {}
  }
  function conv(d, cb) {
    try {
      if (typeof d === 'string') return cb(d);
      if (d instanceof Blob) {
        var r = new FileReader();
        r.onload = function () { cb(String(r.result)); };
        r.readAsText(d);
        return;
      }
      if (d instanceof ArrayBuffer) {
        return cb(new TextDecoder('utf-8').decode(new Uint8Array(d)));
      }
      cb('<unknown>');
    } catch (e) {}
  }
  function attach(w) {
    if (!w || w.__ggeEventsCap) return;
    w.__ggeEventsCap = true;
    w.addEventListener('message', function (ev) { conv(ev.data, push); });
  }

  var list = window.__gge_ws_list || [];
  for (var i = 0; i < list.length; i++) {
    if (list[i] && list[i].readyState === 1) {
      window.__gge_events_cap.ws = list[i];
      attach(list[i]);
    }
  }

  var orig = WebSocket.prototype.send;
  WebSocket.prototype.send = function (d) {
    try {
      window.__gge_events_cap.ws = this;
      attach(this);
      push(d);
    } catch (e) {}
    return orig.apply(this, arguments);
  };
  return 'CAP_INSTALLED list=' + list.length;
})()
"""

WS_STATE_JS = r"""
(function () {
  var c = window.__gge_events_cap;
  if (!c || !c.ws) return 'NO';
  return c.ws.readyState + ':' + String(c.ws.url || '').slice(0, 90);
})()
"""

FRAMES_JS = r"""
JSON.stringify(window.__gge_events_cap ? window.__gge_events_cap.frames : [])
"""

LEVELS_JS = r"""
(function () {
  var out = {legend: null, level: null};
  function num(s) {
    try {
      var n = parseInt(String(s).replace(/[^\d]/g, ''));
      return isNaN(n) ? null : n;
    } catch (e) { return null; }
  }
  function w(o, d) {
    if (!o || d > 16) return;
    try {
      var name = String(o.name || '');
      var text = String(o.text || '').trim();
      if (text) {
        if (name === 'txt_legendLevel') out.legend = num(text);
        if (name === 'txt_level') out.level = num(text);
      }
    } catch (e) {}
    var ch = null;
    try { ch = o.children; } catch (e) {}
    if (ch) for (var i = 0; i < ch.length; i++) w(ch[i], d + 1);
  }
  w(window.uiStage, 0);
  return out;
})()
"""


def _game_target(port=9222):
    targets = requests.get(f"http://127.0.0.1:{port}/json/list", timeout=3).json()
    for target in targets:
        if target.get("type") == "iframe" and "goodgamestudios.com" in target.get("url", ""):
            return target
    raise RuntimeError("No encontre el iframe del juego.")


def _connect(port=9222, timeout=15):
    target = _game_target(port)
    return websocket.create_connection(
        target["webSocketDebuggerUrl"], timeout=timeout, suppress_origin=True
    )


def _eval(ws, expr, msg_id=1, timeout=10):
    ws.send(json.dumps({
        "id": msg_id,
        "method": "Runtime.evaluate",
        "params": {"expression": expr, "returnByValue": True},
    }))
    deadline = time.time() + timeout
    while time.time() < deadline:
        message = json.loads(ws.recv())
        if message.get("id") != msg_id:
            continue
        return message.get("result", {}).get("result", {}).get("value")
    return None


def install_hook(port=9222):
    """
    EN: Install the passive socket hook (idempotent). The socket itself is
        captured on the game's next send (pin/nch).
    ES: Instala el hook pasivo del socket (idempotente). El socket se captura
        en el proximo envio del juego (pin/nch).
    """
    ws = _connect(port)
    try:
        return _eval(ws, HOOK_JS)
    finally:
        ws.close()


def get_player_levels(port=9222):
    """
    EN: Read the legend/player level from the game UI.
    ES: Lee el nivel de leyenda/jugador desde la UI del juego.
    """
    ws = _connect(port)
    try:
        return _eval(ws, LEVELS_JS) or {}
    finally:
        ws.close()


def _decode_frame(frame):
    """
    EN: Base64 `JXh0` frame -> text; plain frame unchanged.
    ES: Frame base64 `JXh0` -> texto; frame plano sin cambios.
    """
    if not frame:
        return ""
    if frame.startswith("JXh0"):
        try:
            return base64.b64decode(frame).decode("utf-8", errors="replace")
        except Exception:
            return ""
    return frame


def _parse_frames(frames):
    """
    EN: Extract the last `sei` JSON and last `core_poe` JSON from frames.
    ES: Extrae el ultimo JSON de `sei` y el ultimo de `core_poe` de los frames.
    """
    sei = None
    poe = None
    for frame in frames or []:
        text = _decode_frame(frame)
        if "xt%sei%" in text and "{" in text:
            try:
                start = text.find("{")
                end = text.rfind("}")
                obj = json.loads(text[start:end + 1])
                if isinstance(obj, dict) and "E" in obj:
                    sei = obj
            except Exception:
                pass
        if "xt%core_poe%" in text and "{" in text:
            try:
                start = text.find("{")
                end = text.rfind("}")
                obj = json.loads(text[start:end + 1])
                if isinstance(obj, dict):
                    poe = obj
            except Exception:
                pass
    return sei, poe


def _send_sei(ws, zone, msg_id=2):
    frame = f"%xt%{zone}%sei%1%{{}}%"
    expr = (
        "(function(){var c=window.__gge_events_cap;"
        "if(!c)return 'NO_CAP';"
        "if(!c.ws||c.ws.readyState!==1)return 'NO_WS';"
        "c.frames=[];"
        f"c.ws.send({json.dumps(frame)});"
        "return 'SENT';})()"
    )
    return _eval(ws, expr, msg_id=msg_id)


def events_from_log(log_path=DEFAULT_LOG):
    """
    EN: Fallback: parse the last `sei`/`core_poe` from the session log tail.
    ES: Fallback: parsea el ultimo `sei`/`core_poe` de la cola del log.
    """
    if not log_path or not os.path.exists(log_path):
        return None
    try:
        size = os.path.getsize(log_path)
        with open(log_path, "rb") as handle:
            handle.seek(max(0, size - 2 * 1024 * 1024))
            tail = handle.read().decode("utf-8", errors="replace")
    except Exception:
        return None

    tail = re.sub(r"\x1b\[[0-9;]*m", "", tail).replace("\r", "")
    index = tail.rfind("[CMD] xt%sei%")
    if index < 0:
        return None
    start = tail.find("{", index)
    if start < 0:
        return None
    try:
        sei, _ = json.JSONDecoder().raw_decode(tail[start:])
    except Exception:
        return None

    poe = None
    index = tail.rfind("xt%core_poe%")
    if index >= 0:
        start = tail.find("{", index)
        if start >= 0:
            try:
                poe, _ = json.JSONDecoder().raw_decode(tail[start:])
            except Exception:
                poe = None
    try:
        base_time = os.path.getmtime(log_path)
    except Exception:
        base_time = time.time()
    return {
        "events": sei.get("E", []) if isinstance(sei, dict) else [],
        "core_poe": poe,
        "source": "log",
        "base_time": base_time,
    }


def fetch_events(port=9222, zone=None, timeout=45, log_path=DEFAULT_LOG,
                 wait_socket=True, verbose=True):
    """
    EN: Fetch `sei` from the live session; fallback to the log.
    ES: Pide `sei` a la sesion viva; fallback al log.
    """
    if not zone:
        zone = "EmpireEx_25"

    ws = None
    try:
        ws = _connect(port)
        hook = _eval(ws, HOOK_JS)
        if verbose and hook:
            print(f"[i] {hook}", file=sys.stderr)

        state = _eval(ws, WS_STATE_JS, msg_id=2) or "NO"
        if wait_socket and not state.startswith("1:"):
            deadline = time.time() + timeout
            last_note = 0
            while time.time() < deadline:
                time.sleep(1.0)
                state = _eval(ws, WS_STATE_JS, msg_id=3) or "NO"
                if state.startswith("1:"):
                    break
                if verbose and time.time() - last_note > 10:
                    print("[i] Esperando el socket del juego para pedir sei...", file=sys.stderr)
                    last_note = time.time()

        if state.startswith("1:"):
            sent = _send_sei(ws, zone, msg_id=4)
            if verbose and sent:
                print(f"[i] sei {sent}", file=sys.stderr)
            deadline = time.time() + 10
            while time.time() < deadline:
                time.sleep(0.5)
                raw = _eval(ws, FRAMES_JS, msg_id=5)
                if not raw:
                    continue
                frames = json.loads(raw)
                sei, poe = _parse_frames(frames)
                if sei:
                    return {
                        "events": sei.get("E", []),
                        "core_poe": poe,
                        "source": "live",
                        "base_time": time.time(),
                    }
    except Exception as exc:
        if verbose:
            print(f"[!] Eventos en vivo: {exc}", file=sys.stderr)
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    fallback = events_from_log(log_path)
    if fallback:
        return fallback
    return {"events": [], "core_poe": None, "source": "none", "base_time": time.time()}
