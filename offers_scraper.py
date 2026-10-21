#!/usr/bin/env python3
"""
EN: Read-only scraper for the in-game "Vista general de ofertas" panel.
    It attaches to the already-running Chrome through CDP (port 9222),
    walks the game's UI tree, extracts every visible offer slot and, when
    the slot exposes an offer VO, reads its rewards/costs/discount straight
    from the client memory. It never sends a game frame and never clicks.

ES: Scraper de solo lectura para el panel "Vista general de ofertas" del
    juego. Se engancha al Chrome que ya esta corriendo por CDP (puerto
    9222), recorre el arbol de UI, extrae cada slot visible y, cuando el
    slot expone un VO de oferta, lee rewards/costos/descuento directo de
    la memoria del cliente. Nunca manda un frame ni hace clicks.

Usage / Uso:
    python offers_scraper.py
    python offers_scraper.py --json
    python offers_scraper.py --watch 5
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime

import requests
import websocket

import gge_catalog
import gge_events

# EN: Friendly names for tooltip/localization keys. Unknown keys fall back
#     to the raw key, so brand-new offers still show up.
# ES: Nombres lindos para claves de tooltip. Las claves desconocidas caen
#     al valor crudo, asi las ofertas nuevas igual salen.
FRIENDLY_TOOLTIP = {
    "dialog_specialOffer_HappyHourTooltip": "Happy Hour / Prime Time privado",
    "dialog_primeday_primesale_enchanterHudIcon_tooltip": "Prime Sale: mejorador de equipo",
    "dialog_unpackedGift__tooltip": "Regalo de Goodgame",
    "dialog_specialOfferBrand_title": "Oferta de marca / carrito",
    "sagaMap_specials_9_title": "Especial del mapa Saga 9",
    "dialog_specialOffer_halloweenSpecial": "Especial de Halloween",
    "dialog_primeday_specialoffer_title": "Oferta especial Prime Day",
    "dialog_specialOfferDeco_title": "Oferta especial de decoracion",
}

FRIENDLY_ICON = {
    "Btn_PrivatePrimeTimeOffer_Hub": "Prime Time privado",
    "Btn_EquipmentEnhancerPrimeSale_Hub": "Prime Sale: mejorador",
    "Btn_EventPackagePrimeSales_Hub": "Paquete de evento Prime Sale",
    "GGSGiftIcon_Hub": "Regalo GGS",
    "Btn_ShoppingCart_Hub": "Carrito de compras",
    "Btn_BoosterSale": "Prime Sale: booster",
    "Btn_PaymentReward_Alien_Hub": "Recompensa de pago: Alien",
    "Btn_PaymentReward_Halloween_Hub": "Recompensa de pago: Halloween",
    "Btn_PaymentReward_Sunday_Hub": "Recompensa de pago: domingo",
    "Btn_POMultiChest_Hub": "Cofre multiple PO",
}

# EN: Friendly names for the internal item/unit ids that appear in rewards.
#     The raw id is always kept in parentheses, so nothing is lost.
# ES: Nombres lindos para los ids internos de items/unidades de los rewards.
#     El id crudo queda entre parentesis, asi no se pierde nada.
FRIENDLY_ITEM = {
    "royalShields": "Escudos reales",
    "royalLadder": "Escaleras reales",
    "royalRam": "Arietes reales",
    "royalBundles": "Manojos reales",
    "royalBanner": "Estandartes reales",
    "Halloween2025TroopMeleeOff": "Tropa Halloween melee ofensiva",
    "Halloween2025TroopRangedOff": "Tropa Halloween ranged ofensiva",
    "ForsakenProtector": "Protector abandonado",
    "ForlornSniper": "Francotirador desolado",
    "HugeKhanTabletChest": "Cofre grande de tablillas del Khan",
    "EliteArrowthrower": "Lanzaflechas de elite",
    "EliteFlamethrower": "Lanzallamas de elite",
    "EliteChalkbomb": "Bomba de tiza de elite",
    "SaleDaysLuckyWheelTicket": "Ticket de ruleta de dias de oferta",
    "Item_Unique_2009": "Skin unica 2009",
}

# EN: JS evaluated inside the game iframe. Finds the panel by its header
#     (the panel exists in the UI tree even while the tooltip is hidden),
#     then walks visible slots. For each slot it also walks the statusIcon
#     VO properties and extracts id/end/discount/rewards/costs.
# ES: JS que corre dentro del iframe del juego. Encuentra el panel por su
#     header (existe en el arbol de UI aunque el tooltip este oculto) y
#     recorre los slots visibles. Por cada slot recorre los VO del
#     statusIcon y extrae id/fin/descuento/rewards/costos.
JS_EXTRACT = r"""
(function () {
  if (!window.uiStage) {
    return JSON.stringify({ok: false, error: "uiStage no existe: el juego no termino de cargar"});
  }

  var header = null;
  function findHeader(o, d) {
    if (header || !o || d > 14) return;
    try {
      if (o.name === "txt_header" && String(o.text || "").indexOf("Vista general") >= 0) {
        header = o;
        return;
      }
    } catch (e) {}
    var ch = null;
    try { ch = o.children; } catch (e) {}
    if (ch) for (var i = 0; i < ch.length; i++) findHeader(ch[i], d + 1);
  }
  findHeader(window.uiStage, 0);

  var panel = null;
  if (header) {
    panel = header;
    while (panel && !(panel.children && panel.children.some(function (c) {
      return c && c.constructor && c.constructor.name === "m";
    }))) {
      panel = panel.parent;
    }
  }

  // EN: Language-agnostic fallback: a container with >=5 offer slots and a
  //     txt_header descendant.
  // ES: Fallback independiente del idioma: un contenedor con >=5 slots de
  //     oferta y un txt_header adentro.
  function hasHeader(o, d) {
    if (!o || d > 5) return false;
    try { if (o.name === "txt_header") return true; } catch (e) {}
    var ch = null; try { ch = o.children; } catch (e) {}
    if (ch) for (var i = 0; i < ch.length; i++) if (hasHeader(ch[i], d + 1)) return true;
    return false;
  }
  function slotCount(o) {
    var n = 0, ch = null;
    try { ch = o.children; } catch (e) {}
    if (!ch) return 0;
    for (var i = 0; i < ch.length; i++) {
      var c = ch[i];
      if (c && c.constructor && c.constructor.name === "m" && c.statusIcon && c.txt_label) n++;
    }
    return n;
  }
  if (!panel) {
    function findPanel(o, d) {
      if (!o || d > 14 || panel) return;
      if (slotCount(o) >= 5 && hasHeader(o, 0)) { panel = o; return; }
      var ch = null; try { ch = o.children; } catch (e) {}
      if (ch) for (var i = 0; i < ch.length; i++) findPanel(ch[i], d + 1);
    }
    findPanel(window.uiStage, 0);
  }
  if (!panel) {
    return JSON.stringify({ok: false, error: "no encontre el panel 'Vista general de ofertas' (proba pasar el mouse por el cofre una vez)"});
  }

  function get(o, k) { try { return o[k]; } catch (e) { return undefined; } }

  function rewardInfo(item) {
    var info = {class: "", amount: item ? get(item, "_amount") : null, id: item ? get(item, "_id") : null};
    try { info.class = item.constructor ? item.constructor.name : ""; } catch (e) {}
    try {
      var unit = get(item, "_unitVO");
      var equip = get(item, "_equipmentVO");
      var currency = get(item, "_xmlCurrencyVO");
      if (unit) {
        info.kind = "unit";
        info.name = get(unit, "_type") || get(unit, "_name") || "";
        info.role = get(unit, "role") || "";
      } else if (equip) {
        info.kind = "equipment";
        info.name = get(equip, "_slotType") || "";
        info.rarity = get(equip, "_rarity") || "";
        info.visual = get(equip, "_visClassName") || "";
      } else if (currency) {
        info.kind = "currency";
        info.name = get(currency, "_name") || "";
      } else if (/Mead/i.test(info.class)) {
        info.kind = "resource"; info.name = "Aguamiel";
      } else if (/Honey/i.test(info.class)) {
        info.kind = "resource"; info.name = "Miel";
      } else if (/Beef/i.test(info.class)) {
        info.kind = "resource"; info.name = "Carne";
      } else if (/Wood/i.test(info.class)) {
        info.kind = "resource"; info.name = "Madera";
      } else if (/Stone/i.test(info.class)) {
        info.kind = "resource"; info.name = "Piedra";
      } else if (/Food/i.test(info.class)) {
        info.kind = "resource"; info.name = "Comida";
      } else if (/ConstructionItem/i.test(info.class)) {
        info.kind = "item"; info.name = "Item de construccion";
      } else if (/LootBox/i.test(info.class)) {
        info.kind = "item"; info.name = "Caja de botin";
      } else {
        info.kind = "other"; info.name = info.class;
      }
    } catch (e) { info.kind = "other"; info.name = info.class; }
    return info;
  }

  function costInfo(item) {
    var cl = "";
    try { cl = item.constructor ? item.constructor.name : ""; } catch (e) {}
    var currency = "";
    if (/C1/.test(cl)) currency = "C1";
    else if (/C2/.test(cl)) currency = "C2";
    return {class: cl, amount: get(item, "_amount"), currency: currency, id: get(item, "_id")};
  }

  function voInfo(vo) {
    var o = {class: ""};
    try { o.class = vo.constructor ? vo.constructor.name : ""; } catch (e) {}
    try {
      var id = vo.id;
      o.id = (typeof id === "function" ? id.call(vo) : id);
      if (o.id === undefined || o.id === null) o.id = get(vo, "_id");
    } catch (e) {}
    try {
      var end = vo.endTimestamp;
      o.end = (typeof end === "function" ? end.call(vo) : end);
      if (o.end === undefined || o.end === null) o.end = get(vo, "_endTimestamp") || get(vo, "_offerEndTimeStamp");
    } catch (e) { o.end = get(vo, "_endTimestamp") || get(vo, "_offerEndTimeStamp"); }
    try {
      var rem = vo.remainingSeconds;
      o.remaining = (typeof rem === "function" ? rem.call(vo) : rem);
    } catch (e) {}
    try { o.event_type = get(vo, "_eventType") || get(vo, "_offerType"); } catch (e) {}
    try { o.discount = get(vo, "_discount"); } catch (e) {}
    try {
      var ap = get(vo, "_additionalParams");
      if (ap) {
        o.cash_discount = get(ap, "_cashDiscount");
        o.type_id = get(ap, "_typeID");
      }
    } catch (e) {}
    try {
      var pids = get(vo, "_packageIDs");
      if (pids) {
        o.package_ids = [];
        for (var i = 0; i < pids.length; i++) o.package_ids.push(pids[i]);
      }
    } catch (e) {}

    try {
      if (typeof vo.getTotalRewardListFromOfferVO === "function") {
        var rl = vo.getTotalRewardListFromOfferVO();
        var rlist = rl && (get(rl, "_list") || get(rl, "list"));
        if (rlist) o.rewards = Array.from(rlist).map(rewardInfo);
      }
    } catch (e) { o.rewards_error = String(e); }

    try {
      if (typeof vo.getCostsForOfferAcception === "function") {
        var cl = vo.getCostsForOfferAcception();
        var clist = cl && (get(cl, "_list") || get(cl, "list"));
        if (clist) o.costs = Array.from(clist).map(costInfo);
      }
    } catch (e) { o.costs_error = String(e); }

    return o;
  }

  var slots = [];
  for (var i = 0; i < panel.children.length; i++) {
    var c = panel.children[i];
    if (!c || !c.constructor || c.constructor.name !== "m" || !c.visible) continue;
    var si = get(c, "statusIcon");
    var lbl = get(c, "txt_label");
    var mc = get(c, "mc_hit");

    var vos = [];
    if (si) {
      try {
        Object.getOwnPropertyNames(si).forEach(function (k) {
          if (k === "textVO" || !/VO$/.test(k)) return;
          var vo = si[k];
          if (!vo) return;
          vos.push({key: k, info: voInfo(vo)});
        });
      } catch (e) {}
    }

    var gp = null;
    try {
      var p = c.localToGlobal(0, 0);
      gp = {x: Math.round(p.x), y: Math.round(p.y)};
    } catch (e) {}

    slots.push({
      index: i,
      x: Math.round(get(c, "x") || 0),
      y: Math.round(get(c, "y") || 0),
      global: gp,
      timer: lbl ? String(get(lbl, "text") || "") : "",
      status_class: si && si.constructor ? si.constructor.name : "",
      inner_icon: si ? String(get(si, "_innerIconClassName") || "") : "",
      tooltip_id: si ? String(get(si, "_tooltipId") || "") : "",
      hit_tooltip: mc ? String(get(mc, "toolTipText") || "") : "",
      is_new: si ? !!get(si, "_isNew") : false,
      vos: vos
    });
  }

  return JSON.stringify({
    ok: true,
    panel_visible: !!panel.visible,
    count: slots.length,
    slots: slots
  });
})()
"""

# EN: Offers that must not be clicked automatically: their onClick sends a
#     game action (claiming a gift) instead of opening a read-only detail.
# ES: Ofertas que no hay que clickear automatico: su onClick manda una
#     accion (reclamar regalo) en vez de abrir un detalle de solo lectura.
SKIP_ICONS = {"GGSGiftIcon_Hub"}

# EN: Fallback close position for external preloader dialogs (the shopping
#     cart): their X is part of the external clip, not a named display object.
# ES: Posicion de cierre fallback para dialogos de preloader externo (el
#     carrito): su X es parte del clip externo, no un objeto con nombre.
GENERIC_CLOSE_XY = (1322, 210)

# EN: Global position of the offer-hub button (the chest that opens the
#     "Vista general" tooltip). Derived from the UI tree, with a fallback.
# ES: Posicion global del boton del cofre que abre el tooltip "Vista
#     general". Se deriva del arbol de UI, con fallback.
JS_HUB = r"""
(function () {
  var header = null;
  function f(o, d) {
    if (header || !o || d > 14) return;
    try {
      if (o.name === "txt_header" && String(o.text || "").indexOf("Vista general") >= 0) {
        header = o; return;
      }
    } catch (e) {}
    var ch = null; try { ch = o.children; } catch (e) {}
    if (ch) for (var i = 0; i < ch.length; i++) f(ch[i], d + 1);
  }
  f(window.uiStage, 0);
  var panel = header;
  while (panel && !(panel.children && panel.children.some(function (c) {
    return c && c.constructor && c.constructor.name === "m";
  }))) panel = panel.parent;
  if (panel && panel.parent && panel.parent.children && panel.parent.children[1]) {
    try {
      var p = panel.parent.children[1].localToGlobal(0, -18);
      return {x: Math.round(p.x), y: Math.round(p.y)};
    } catch (e) {}
  }
  return {x: 1405, y: 915};
})()
"""

# EN: Read the generic offer/discount detail dialog. It returns the named
#     fields (description, prices, discount, timer), the booster/building
#     texts and the global coordinates of the close X.
# ES: Lee el dialogo generico de detalle de oferta/descuento. Devuelve los
#     campos nombrados (descripcion, precios, descuento, timer), los textos
#     del booster/edificio y las coordenadas globales de la X de cerrar.
JS_READ_DIALOG = r"""
(function () {
  var dialog = null;
  function find(o, d) {
    if (dialog || !o || d > 16) return;
    try {
      if (o.constructor && o.constructor.name !== "TextField" && o.visible !== false &&
          o.children && o.children.some(function (c) { return c && c.name === "btn_close"; })) {
        dialog = o; return;
      }
    } catch (e) {}
    var ch = null; try { ch = o.children; } catch (e) {}
    if (ch) for (var i = 0; i < ch.length; i++) find(ch[i], d + 1);
  }
  find(window.uiStage, 0);
  if (!dialog) return {open: false};

  function get(o, k) { try { return o[k]; } catch (e) { return undefined; } }
  function textOf(o) {
    if (!o) return "";
    try { return String(o.text || "").trim(); } catch (e) { return ""; }
  }
  function textsOf(o, d, acc) {
    if (!o || d > 5) return acc;
    try {
      var s = String(o.text || "").trim();
      if (s && acc.indexOf(s) < 0) acc.push(s);
    } catch (e) {}
    var ch = null; try { ch = o.children; } catch (e) {}
    if (ch) for (var i = 0; i < ch.length; i++) textsOf(ch[i], d + 1, acc);
    return acc;
  }

  function firstText(o) {
    var t = textOf(o);
    if (t) return t;
    var arr = textsOf(o, 0, []);
    return arr.length ? arr[0] : "";
  }

  var fields = {};
  ["txt_copy", "txt_offer", "mc_costs", "mc_old_costs", "mc_percentOff",
   "mc_time", "mc_limited_offer"].forEach(function (k) {
    var o = get(dialog, k);
    if (o) fields[k] = firstText(o);
  });

  var out = {open: true, fields: fields, texts: textsOf(dialog, 0, [])};

  var booster = get(dialog, "mc_booster_container");
  if (booster) {
    out.title = textOf(get(booster, "txt_title"));
    out.effect = textsOf(get(booster, "mc_bottom_rewards"), 0, []);
  }
  var building = get(dialog, "mc_buildingClip");
  if (building) {
    out.building = {
      name: textOf(get(building, "txt_name")),
      level: textOf(get(building, "txt_level"))
    };
  }
  var pkg = get(dialog, "mc_package_container");
  if (pkg) out.package_texts = textsOf(pkg, 0, []);
  var prime = get(dialog, "prime_sale_list");
  if (prime) out.prime_texts = textsOf(prime, 0, []);

  try {
    var b = get(dialog, "btn_close");
    if (b) {
      var bb = b.getBounds();
      var p = b.localToGlobal(bb.x + bb.width / 2, bb.y + bb.height / 2);
      out.close = {x: Math.round(p.x), y: Math.round(p.y)};
    }
  } catch (e) {}

  return out;
})()
"""

JS_SLOTS_LIVE = r"""
(function () {
  var header = null;
  function f(o, d) {
    if (header || !o || d > 14) return;
    try {
      if (o.name === "txt_header" && String(o.text || "").indexOf("Vista general") >= 0) {
        header = o; return;
      }
    } catch (e) {}
    var ch = null; try { ch = o.children; } catch (e) {}
    if (ch) for (var i = 0; i < ch.length; i++) f(ch[i], d + 1);
  }
  f(window.uiStage, 0);
  var panel = header;
  while (panel && !(panel.children && panel.children.some(function (c) {
    return c && c.constructor && c.constructor.name === "m";
  }))) panel = panel.parent;
  if (!panel) return [];
  var out = [];
  for (var i = 0; i < panel.children.length; i++) {
    var c = panel.children[i];
    if (!c || !c.constructor || c.constructor.name !== "m" || !c.visible) continue;
    var center = null;
    try {
      var h = c.mc_hit || c;
      var b = h.getBounds();
      var p = h.localToGlobal(b.x + b.width / 2, b.y + b.height / 2);
      center = {x: Math.round(p.x), y: Math.round(p.y)};
    } catch (e) {}
    out.push({
      i: i,
      icon: String(c.statusIcon && c.statusIcon._innerIconClassName || ""),
      timer: c.txt_label ? String(c.txt_label.text || "") : "",
      center: center
    });
  }
  return out;
})()
"""

JS_VISIBLE_TEXTS = r"""
(function () {
  var out = [];
  function w(o, d) {
    if (!o || d > 16 || out.length > 400) return;
    try {
      if (o.constructor && o.constructor.name === "TextField" && o.visible !== false) {
        var t = String(o.text || "").trim();
        if (t && out.indexOf(t) < 0) out.push(t);
      }
    } catch (e) {}
    var ch = null; try { ch = o.children; } catch (e) {}
    if (ch) for (var i = 0; i < ch.length; i++) w(ch[i], d + 1);
  }
  w(window.uiStage, 0);
  return out;
})()
"""

JS_HANDLER_STATE = r"""
(function () {
  var g = window.gamestage.children[0];
  var dh = g.bDialogHandler;
  var p = dh._dialogVO && dh._dialogVO.properties;
  return {
    displaying: !!dh.isDisplayingAnyDialog,
    hideFunction: !!(p && typeof p.hideFunction === "function"),
    propClass: p && p.constructor ? p.constructor.name : ""
  };
})()
"""

JS_HIDE_DIALOG = r"""
(function () {
  var g = window.gamestage.children[0];
  var dh = g.bDialogHandler;
  var p = dh._dialogVO && dh._dialogVO.properties;
  if (p && typeof p.hideFunction === "function") {
    p.hideFunction();
    return !dh.isDisplayingAnyDialog;
  }
  return false;
})()
"""

JS_DIALOG_STATE = r"""
(function () {
  var found = false;
  function find(o, d) {
    if (found || !o || d > 16) return;
    try {
      if (o.constructor && o.constructor.name !== "TextField" && o.visible !== false &&
          o.children && o.children.some(function (c) { return c && c.name === "btn_close"; })) {
        found = true; return;
      }
    } catch (e) {}
    var ch = null; try { ch = o.children; } catch (e) {}
    if (ch) for (var i = 0; i < ch.length; i++) find(ch[i], d + 1);
  }
  find(window.uiStage, 0);
  return found;
})()
"""


def _friendly(slot):
    """
    EN: Human label for one slot: tooltip key first, icon class second.
    ES: Etiqueta legible para un slot: primero la clave de tooltip,
        despues la clase del icono.
    """
    return (
        FRIENDLY_TOOLTIP.get(slot.get("tooltip_id", ""))
        or FRIENDLY_ICON.get(slot.get("inner_icon", ""))
        or slot.get("tooltip_id")
        or slot.get("inner_icon")
        or slot.get("status_class")
        or "?"
    )


def _primary_vo(slot):
    """
    EN: Pick the richest VO of a slot: first with rewards, else the first.
    ES: Elegir el VO mas rico del slot: el primero con rewards, si no el primero.
    """
    vos = slot.get("vos") or []
    if not vos:
        return None
    for item in vos:
        info = item.get("info") or {}
        if info.get("rewards") or info.get("costs"):
            return info
    return vos[0].get("info")


def _fmt_num(value):
    """
    EN: Human number: 99999 -> 99.999, 1.5 -> 1,5.
    ES: Numero legible: 99999 -> 99.999, 1.5 -> 1,5.
    """
    if value is None:
        return "?"
    try:
        f = float(value)
        if f.is_integer():
            return f"{int(f):,}".replace(",", ".")
        return f"{f:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(value)


def _fmt_ts(ms):
    """
    EN: Epoch milliseconds -> local date/time string.
    ES: Milisegundos epoch -> fecha/hora local.
    """
    if not ms:
        return "?"
    try:
        return datetime.fromtimestamp(float(ms) / 1000.0).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ms)


def _fmt_ts_s(ts):
    """
    EN: Epoch seconds -> local date/time (events use seconds).
    ES: Segundos epoch -> fecha/hora local (los eventos usan segundos).
    """
    if not ts:
        return "?"
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)


def _reward_line(reward):
    """
    EN: One reward as a readable bullet.
    ES: Un reward como vineta legible.
    """
    amount = _fmt_num(reward.get("amount"))
    kind = reward.get("kind")
    raw_name = reward.get("name") or reward.get("class") or "?"
    friendly = FRIENDLY_ITEM.get(raw_name)
    name = f"{friendly} ({raw_name})" if friendly else raw_name
    if kind == "unit":
        role = reward.get("role")
        return f"{amount}x {name}" + (f" ({role})" if role else "")
    if kind == "equipment":
        visual_raw = reward.get("visual")
        visual = FRIENDLY_ITEM.get(visual_raw, visual_raw)
        extra = ", ".join(x for x in [reward.get("rarity"), visual] if x)
        return f"{amount}x Equipo {name}" + (f" ({extra})" if extra else "")
    if kind == "item":
        rid = reward.get("id")
        return f"{amount}x {name}" + (f" (id {rid})" if rid is not None else "")
    return f"{amount}x {name}"


def _cost_line(cost):
    """
    EN: One cost as a readable line. C1 = rubies/cash, C2 = coins/gold.
    ES: Un costo como linea legible. C1 = rubies/cash, C2 = monedas/oro.
    """
    amount = _fmt_num(cost.get("amount"))
    currency = cost.get("currency") or ""
    label = {"C1": "C1 (cash)", "C2": "C2 (rubies)"}.get(currency, currency)
    return f"{amount} {label}".strip()


def _find_game_target(port):
    """
    EN: Find the goodgamestudios iframe target in Chrome's debug targets.
    ES: Busca el target del iframe de goodgamestudios en los targets de Chrome.
    """
    try:
        targets = requests.get(f"http://127.0.0.1:{port}/json/list", timeout=3).json()
    except Exception as exc:
        raise RuntimeError(
            f"No pude hablar con Chrome en el puerto {port} ({exc}). "
            "¿Esta corriendo main.py?"
        ) from exc

    for target in targets:
        url = target.get("url", "")
        if target.get("type") == "iframe" and "goodgamestudios.com" in url:
            return target
    raise RuntimeError(
        "No encontre el iframe del juego. ¿Esta logueado y con el castillo abierto?"
    )


def scrape(port=9222):
    """
    EN: Connect by CDP and return the parsed offers snapshot.
    ES: Conecta por CDP y devuelve el snapshot de ofertas ya parseado.
    """
    target = _find_game_target(port)
    ws = websocket.create_connection(
        target["webSocketDebuggerUrl"],
        timeout=15,
        suppress_origin=True,
    )
    try:
        ws.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": JS_EXTRACT, "returnByValue": True},
        }))
        deadline = time.time() + 15
        while time.time() < deadline:
            message = json.loads(ws.recv())
            if message.get("id") != 1:
                continue
            if "error" in message:
                raise RuntimeError(f"CDP error: {message['error']}")
            value = message.get("result", {}).get("result", {}).get("value")
            if value is None:
                raise RuntimeError("Runtime.evaluate no devolvio valor")
            data = json.loads(value)
            if not data.get("ok"):
                raise RuntimeError(data.get("error", "error desconocido"))
            return data
        raise RuntimeError("Timeout esperando la respuesta de Runtime.evaluate")
    finally:
        try:
            ws.close()
        except Exception:
            pass


def _has_vo_content(slot):
    """
    EN: True when the slot VO already exposes rewards or costs.
    ES: True cuando el VO del slot ya expone rewards o costos.
    """
    for item in slot.get("vos") or []:
        info = item.get("info") or {}
        if info.get("rewards") or info.get("costs"):
            return True
    return False


def _collect_details(data, port=9222):
    """
    EN: For offers whose VO has no content, open the in-game detail with a
        trusted Selenium click, read the dialog generically and close it
        with a trusted click on the X. Selenium attaches to the Chrome that
        main.py already has open; it does not launch a new browser.
    ES: Para las ofertas cuyo VO no trae contenido, abre el detalle con un
        click confiable de Selenium, lee el dialogo de forma generica y lo
        cierra con un click confiable en la X. Selenium se engancha al
        Chrome que ya abrio main.py; no lanza un navegador nuevo.
    """
    targets = [
        slot for slot in data.get("slots", [])
        if not _has_vo_content(slot)
        and slot.get("inner_icon") not in SKIP_ICONS
        and slot.get("global")
    ]
    if not targets:
        return data

    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.action_chains import ActionChains
    except Exception as exc:
        print(f"[!] Selenium no disponible: {exc}", file=sys.stderr)
        return data

    driver = None
    try:
        options = webdriver.ChromeOptions()
        options.debugger_address = f"127.0.0.1:{port}"
        driver = webdriver.Chrome(options=options)
        driver.switch_to.frame(driver.find_element(By.CSS_SELECTOR, "iframe#game"))
        body = driver.find_element(By.TAG_NAME, "body")
        width, height = body.size["width"], body.size["height"]

        def hover(x, y):
            ActionChains(driver).move_to_element(body).move_by_offset(
                x - width / 2, y - height / 2
            ).perform()

        # EN: Move from the current pointer position instead of resetting to
        #     the body center: resetting closes the hover panel before the
        #     click reaches the slot.
        # ES: Moverse desde la posicion actual del puntero en vez de resetear
        #     al centro del body: resetear cierra el panel de hover antes de
        #     que el click llegue al slot.
        pointer = [0, 0]

        def move_click(x, y):
            # EN: Move first, let the slot register the hover, then click.
            # ES: Mover primero, dejar que el slot registre el hover, y
            #     recien despues clickear.
            ActionChains(driver).move_by_offset(
                x - pointer[0], y - pointer[1]
            ).perform()
            pointer[0], pointer[1] = x, y
            time.sleep(0.3)
            ActionChains(driver).click().perform()

        hub = driver.execute_script("return (" + JS_HUB + ")") or {"x": 1405, "y": 915}

        for slot in targets:
            g = slot["global"]
            hover(hub["x"], hub["y"])
            pointer[0], pointer[1] = hub["x"], hub["y"]
            time.sleep(1.2)

            # EN: The panel slides while opening, so re-read the live hit
            #     center after the hover instead of using the pre-hover
            #     coordinate.
            # ES: El panel se desliza al abrirse, asi que releo el centro
            #     del hit area despues del hover en vez de usar la
            #     coordenada de antes.
            live = driver.execute_script("return (" + JS_SLOTS_LIVE + ")") or []
            center = None
            for item in live:
                if item.get("i") == slot.get("index"):
                    center = item.get("center")
                    break
            if not center:
                for item in live:
                    if item.get("icon") == slot.get("inner_icon"):
                        center = item.get("center")
                        break
            if not center:
                center = {"x": g["x"], "y": g["y"] - 12}

            # EN: Baseline of visible texts before opening, to isolate the
            #     dialog texts when it has no btn_close (external preloaders).
            # ES: Base de textos visibles antes de abrir, para aislar los del
            #     dialogo cuando no tiene btn_close (preloaders externos).
            baseline = set(driver.execute_script("return (" + JS_VISIBLE_TEXTS + ")") or [])

            move_click(center["x"], center["y"])
            time.sleep(1.8)

            detail = driver.execute_script("return (" + JS_READ_DIALOG + ")")
            attempts = 0
            while (not detail or not detail.get("open")) and attempts < 5:
                time.sleep(1.0)
                detail = driver.execute_script("return (" + JS_READ_DIALOG + ")")
                attempts += 1
                if detail and detail.get("open"):
                    break
                state = driver.execute_script("return (" + JS_HANDLER_STATE + ")") or {}
                if state.get("displaying"):
                    texts = driver.execute_script("return (" + JS_VISIBLE_TEXTS + ")") or []
                    new_texts = [t for t in texts if t not in baseline]
                    if not new_texts:
                        # EN: The diff can be empty if the dialog reuses texts
                        #     or the baseline was taken while it was loading.
                        # ES: El diff puede quedar vacio si el dialogo reusa
                        #     textos o la base se tomo mientras cargaba.
                        new_texts = texts[-40:]
                    if new_texts:
                        detail = {
                            "open": True,
                            "generic": True,
                            "texts": new_texts,
                            "fields": {},
                            "close_via": "hideFunction" if state.get("hideFunction") else None,
                        }
                        break

            if not detail or not detail.get("open"):
                print(
                    f"[!] No abrio el detalle de {slot.get('inner_icon')}",
                    file=sys.stderr,
                )
                continue

            slot["detail"] = detail

            def dialog_open():
                st = driver.execute_script("return (" + JS_HANDLER_STATE + ")") or {}
                return bool(driver.execute_script("return (" + JS_DIALOG_STATE + ")")) or bool(st.get("displaying"))

            closed = False
            for _attempt in range(3):
                close = detail.get("close") if detail else None
                if close:
                    move_click(close["x"], close["y"])
                else:
                    if not driver.execute_script("return (" + JS_HIDE_DIALOG + ")"):
                        move_click(GENERIC_CLOSE_XY[0], GENERIC_CLOSE_XY[1])
                time.sleep(0.9)
                if not dialog_open():
                    closed = True
                    break

                # EN: The dialog may have moved/animated; refresh the close
                #     coordinates and try again.
                # ES: El dialogo pudo moverse/animarse; refresco las
                #     coordenadas de cierre y reintento.
                fresh = driver.execute_script("return (" + JS_READ_DIALOG + ")")
                if fresh and fresh.get("open"):
                    detail = fresh
                if driver.execute_script("return (" + JS_HIDE_DIALOG + ")"):
                    time.sleep(0.5)
                    if not dialog_open():
                        closed = True
                        break

            if not closed:
                print(
                    f"[!] El detalle de {slot.get('inner_icon')} no se cerro",
                    file=sys.stderr,
                )
                break
    except Exception as exc:
        print(f"[!] No pude leer los detalles: {exc}", file=sys.stderr)
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

    return data


def _numeric_signals(texts):
    """
    EN: All integers shown in the cart dialog (dots as thousands).
    ES: Todos los enteros que muestra el dialogo del carrito (puntos de miles).
    """
    nums = set()
    for text in texts or []:
        for token in re.findall(r"\d[\d.]*", str(text)):
            try:
                nums.add(int(token.replace(".", "")))
            except Exception:
                pass
    return nums


def _enrich_with_events(data, events, catalog, port=9222):
    """
    EN: Attach structured `sei` data to the matching UI slots:
        cart (EID 90) with the exact variant, Prime Time (core_poe).
    ES: Adjunta datos estructurados de `sei` a los slots que corresponden:
        carrito (EID 90) con la variante exacta, Prime Time (core_poe).
    """
    base = events.get("base_time") or time.time()
    by_eid = {
        event.get("EID"): event
        for event in events.get("events", [])
        if isinstance(event, dict)
    }
    try:
        levels = gge_events.get_player_levels(port)
    except Exception:
        levels = {}
    level = levels.get("legend") or levels.get("level")
    slots = data.get("slots", [])

    cart_event = by_eid.get(90)
    if cart_event:
        slot = next(
            (s for s in slots if s.get("inner_icon") == "Btn_ShoppingCart_Hub"), None
        )
        if slot:
            detail = slot.get("detail") or {}
            signals = _numeric_signals(detail.get("texts") or [])
            if signals:
                variant = catalog.cart_variant(
                    cart_event.get("TID") or [],
                    level=level,
                    signal_numbers=signals,
                )
                if variant:
                    slot["cart"] = {
                        "event": cart_event,
                        "variant": variant,
                        "cost": cart_event.get("C2"),
                        "uses": cart_event.get("LIM"),
                        "end": base + int(cart_event.get("RS") or 0),
                        "level": level,
                    }

    poe = events.get("core_poe")
    if poe:
        slot = next(
            (s for s in slots if s.get("inner_icon") == "Btn_PrivatePrimeTimeOffer_Hub"),
            None,
        )
        if slot:
            slot["prime"] = catalog.format_prime_time(poe, base_time=base)

    return data


def print_table(data):
    """
    EN: Print the offer snapshot as a table plus one detail block per offer.
    ES: Imprime el snapshot como tabla mas un bloque de detalle por oferta.
    """
    slots = data.get("slots", [])
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[{stamp}] Vista general de ofertas — {len(slots)} ofertas"
          f" (panel {'visible' if data.get('panel_visible') else 'oculto'})\n")
    if not slots:
        print("(sin ofertas visibles)")
        return

    print(f"{'#':>2}  {'Vence':<11}  {'Tipo':<34}  Icono")
    print("-" * 96)
    for n, slot in enumerate(slots, 1):
        print(
            f"{n:>2}  {slot.get('timer', ''):<11}  "
            f"{_friendly(slot):<34}  {slot.get('inner_icon', '')}"
        )

    print("\nDetalle:")
    for n, slot in enumerate(slots, 1):
        vo = _primary_vo(slot)
        bits = []
        if vo:
            if vo.get("id") is not None:
                bits.append(f"ID {vo.get('id')}")
            if vo.get("end"):
                bits.append(f"termina {_fmt_ts(vo.get('end'))}")
            if vo.get("discount"):
                bits.append(f"descuento {vo.get('discount')}%")
            if vo.get("cash_discount"):
                bits.append(f"cash discount {vo.get('cash_discount')}%")
            if vo.get("event_type"):
                bits.append(f"tipo {vo.get('event_type')}")
            if vo.get("package_ids"):
                bits.append("paquetes " + ", ".join(str(x) for x in vo["package_ids"]))
        head = f" {n:>2}) {_friendly(slot)}"
        if bits:
            head += " — " + " · ".join(bits)
        print(head)

        cart = slot.get("cart")
        if cart:
            variant = cart.get("variant") or {}
            line = f"      Carrito: {_fmt_num(cart.get('cost'))} rubies"
            if cart.get("uses") is not None:
                line += f" · {cart['uses']} usos"
            line += f" · termina {_fmt_ts_s(cart.get('end'))}"
            print(line)
            for side in variant.get("sides", []):
                print(f"        Lado {side['side']}: " + " · ".join(side["options"]))
            continue

        prime = slot.get("prime")
        if prime:
            extra = f" · termina {_fmt_ts_s(prime.get('end'))}" if prime.get("end") else ""
            print(f"      Prime Time: +{prime.get('bonus')}%{extra}")

        rewards = (vo or {}).get("rewards") or []
        costs = (vo or {}).get("costs") or []
        if rewards:
            print("      Contenido:")
            for reward in rewards:
                print(f"        - {_reward_line(reward)}")
        if costs:
            print("      Precio: " + " + ".join(_cost_line(c) for c in costs))

        detail = slot.get("detail")
        if detail and detail.get("generic"):
            print("      Detalle (texto del dialogo):")
            texts = detail.get("texts") or []
            with_letters = [t for t in texts if any(ch.isalpha() for ch in t)]
            without_letters = [t for t in texts if not any(ch.isalpha() for ch in t)]
            for t in (with_letters + without_letters)[:18]:
                print("        - " + t)
        elif detail:
            fields = detail.get("fields") or {}
            packages = detail.get("package_texts") or []
            title = detail.get("title") or (packages[0] if packages else "")
            if not title:
                title = (detail.get("building") or {}).get("name") or ""
            if not title or title.lower() == "oferta especial":
                alt = fields.get("txt_offer") or ""
                if alt and alt.lower() != "oferta especial":
                    title = alt
            if title and title.lower() != "oferta especial":
                print(f"      Detalle: {title}")

            effect = detail.get("effect") or []
            if effect:
                print("        Efecto: " + " · ".join(effect))

            price = fields.get("mc_costs") or ""
            old = fields.get("mc_old_costs") or ""
            raw_disc = fields.get("mc_percentOff") or ""
            offer_text = fields.get("mc_limited_offer") or ""

            discount = ""
            for candidate in (raw_disc, offer_text):
                c = candidate.strip()
                if "%" in c or c.startswith("-"):
                    discount = candidate
                    break

            if price or old:
                line = "        Precio: " + (price or "?")
                if old:
                    line += f" (antes {old})"
                if discount:
                    line += f" · {discount}"
                print(line)
            elif discount:
                print("        Descuento: " + discount)

            if raw_disc and raw_disc != discount:
                print("        Texto: " + raw_disc)
            if offer_text and offer_text != discount:
                print("        Oferta: " + offer_text)

            if fields.get("mc_time"):
                print("        Timer: " + fields["mc_time"])
            if fields.get("txt_copy"):
                print("        Descripción: " + fields["txt_copy"])

            if packages:
                extra = packages[1:] if title == packages[0] else packages
                if extra:
                    print("        Paquete: " + " · ".join(extra[:8]))
            if detail.get("prime_texts"):
                print("        Items: " + " · ".join(detail["prime_texts"][:8]))

            meaningful = [
                t for t in (detail.get("texts") or [])
                if t not in {
                    "Oferta especial", "¡Muéstrame!", "Agregar rubies",
                    "Agregar rubíes", "Oferta termina:", "Bonus de lealtad",
                    "Exclusivo para", "--Zoto--",
                }
                and len(t) > 2
            ]
            if not any([
                title and title.lower() != "oferta especial", effect, price, old,
                discount, fields.get("mc_time"), fields.get("txt_copy"),
            ]) and meaningful:
                print("        " + " · ".join(meaningful[:10]))
        elif not rewards and not costs:
            if slot.get("inner_icon") in SKIP_ICONS:
                print("      (no se abre automatico: su click reclama el regalo)")
            else:
                print("      (sin contenido en el VO: esta oferta abre dialogo/shop)")
    print(flush=True)


def _signature(data):
    """
    EN: Stable identity of the offer set (timers excluded on purpose).
    ES: Identidad estable del conjunto de ofertas (sin timers a proposito).
    """
    return tuple(
        (s.get("tooltip_id", ""), s.get("inner_icon", ""), s.get("status_class", ""))
        for s in data.get("slots", [])
    )


def watch(port, interval):
    """
    EN: Poll forever and report when the offer set changes (expires/new).
    ES: Poll infinito y avisa cuando cambia el conjunto (vence/nueva).
    """
    print(f"Vigilando ofertas cada {interval}s. Ctrl+C para cortar.")
    previous = None
    while True:
        try:
            data = scrape(port)
        except Exception as exc:
            print(f"[{datetime.now():%H:%M:%S}] error: {exc}", file=sys.stderr)
            time.sleep(interval)
            continue

        signature = _signature(data)
        if previous is None:
            print_table(data)
        elif signature != previous:
            old = set(previous)
            new = set(signature)
            for item in new - old:
                print(f"[{datetime.now():%H:%M:%S}] NUEVA: {item[0] or item[1]}")
            for item in old - new:
                print(f"[{datetime.now():%H:%M:%S}] CERRADA: {item[0] or item[1]}")
            print_table(data)
        previous = signature
        time.sleep(interval)


def _print_events(port=9222):
    """
    EN: Print the structured `sei` events (global offers/cart/prime time).
    ES: Imprime los eventos estructurados de `sei` (ofertas globales/carrito/prime time).
    """
    events = gge_events.fetch_events(port, wait_socket=False, verbose=True)
    catalog = gge_catalog.get_catalog(verbose=True)
    base = events.get("base_time") or time.time()
    known = {7, 75, 90, 997, 998, 999}

    print(f"\nEventos de oferta (fuente: {events.get('source')}):")
    count = 0
    for event in events.get("events", []):
        eid = event.get("EID")
        if eid not in known:
            continue
        if eid == 90:
            print("[EID 90] Carrito de compras")
            if event.get("C2") is not None:
                print(f"  Costo: {_fmt_num(event.get('C2'))} rubies")
            if event.get("LIM") is not None:
                print(f"  Usos: {event.get('LIM')}")
            if event.get("RS") is not None:
                print(f"  Termina: {_fmt_ts_s(base + int(event.get('RS') or 0))}")
            print("  (el desglose exacto por variante sale con --details)")
            count += 1
            continue
        info = catalog.format_event(event, base_time=base)
        print(f"[EID {info['eid']}] {info['title']}")
        for line in info["lines"]:
            print("  " + line)
        count += 1

    poe = events.get("core_poe")
    if poe:
        info = catalog.format_prime_time(poe, base_time=base)
        print(f"[core_poe] {info['title']}")
        for line in info["lines"]:
            print("  " + line)
        count += 1

    if not count:
        print("(sin eventos de oferta en este momento)")
    print(flush=True)


def main():
    # EN: Line-buffered output so --watch prints even when piped.
    # ES: Salida con line buffering para que --watch imprima aunque este piped.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="Scraper de solo lectura de la Vista general de ofertas (GGE)."
    )
    parser.add_argument("--port", type=int, default=9222,
                        help="puerto de debugging de Chrome (default 9222)")
    parser.add_argument("--json", action="store_true",
                        help="imprimir el snapshot como JSON")
    parser.add_argument("--details", action="store_true",
                        help="abrir las ofertas sin VO y leer su detalle (Selenium)")
    parser.add_argument("--events", action="store_true",
                        help="mostrar eventos sei (ofertas globales/carrito/prime time)")
    parser.add_argument("--watch", type=int, metavar="SEGUNDOS",
                        help="poll cada N segundos y avisar cambios")
    args = parser.parse_args()

    if args.events:
        _print_events(args.port)
        return

    if args.watch:
        if args.details:
            print("[i] --details se ignora con --watch.", file=sys.stderr)
        try:
            watch(args.port, args.watch)
        except KeyboardInterrupt:
            print("\nCortado.")
        return

    try:
        data = scrape(args.port)
    except Exception as exc:
        print(f"[!] {exc}", file=sys.stderr)
        sys.exit(1)

    if args.details:
        try:
            gge_events.install_hook(args.port)
        except Exception as exc:
            print(f"[!] Hook de eventos: {exc}", file=sys.stderr)
        data = _collect_details(data, args.port)
        try:
            events = gge_events.fetch_events(args.port, wait_socket=False, verbose=False)
            catalog = gge_catalog.get_catalog(verbose=False)
            data = _enrich_with_events(data, events, catalog, args.port)
        except Exception as exc:
            print(f"[!] Eventos: {exc}", file=sys.stderr)

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print_table(data)


if __name__ == "__main__":
    main()
