#!/usr/bin/env python3
"""
EN: Public Goodgame Empire items catalog + event formatters.
    It downloads/caches items_v<version>.json and resolves:
      - shoppingCarts + rewards -> readable cart options
      - buildings -> name and discounted cost
      - units -> unit names for cart rewards
    It is read-only: only public GET requests, no game session needed.

ES: Catalogo publico de items de Goodgame Empire + formateadores de eventos.
    Descarga/cachea items_v<version>.json y resuelve:
      - shoppingCarts + rewards -> opciones del carrito legibles
      - buildings -> nombre y costo con descuento
      - units -> nombres de unidades de los rewards del carrito
    Es de solo lectura: solo GET publicos, no necesita sesion del juego.
"""

import collections
import json
import os
import re
import sys
import time

import requests

ITEMS_VERSION_URL = (
    "https://empire-html5.goodgamestudios.com/default/items/ItemsVersion.properties"
)
ITEMS_URL = (
    "https://empire-html5.goodgamestudios.com/default/items/items_v{version}.json"
)
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".gge-cache")

# EN: Labels for the reward effect fields used by shopping carts.
# ES: Etiquetas para los campos de efecto que usan los carritos.
EFFECT_LABELS = {
    "add60MinSkip": "saltos de 60 min",
    "add30MinSkip": "saltos de 30 min",
    "add10MinSkip": "saltos de 10 min",
    "add5MinSkip": "saltos de 5 min",
    "addLuckyWheelTicket": "tickets de la ruleta",
    "add5HourSkip": "saltos de 5 h",
    "add24HourSkip": "saltos de 24 h",
    "addPegasusTicket": "tickets Pegaso",
    "addSaleDaysLuckyWheelTicket": "tickets ruleta",
    "addFatKingToken": "Fat King tokens",
    "mead": "aguamiel",
    "honey": "miel",
    "beef": "carne",
    "wood": "madera",
    "stone": "piedra",
    "food": "comida",
    "coins": "monedas",
    "rubies": "rubies",
    "cash": "rubies",
}

# EN: Known EID 75 BID values (small fallback; the rest is generic).
# ES: BID conocidos del EID 75 (fallback chico; el resto es generico).
BID_NAMES = {
    "[2]": "Capataz",
    "[6]": "Merodeador",
    "[10]": "Sargento instructor",
}

PRIME_TIME_EIDS = {
    997: "Prime Time (Lacis)",
    998: "Prime Time (RE)",
    999: "Prime Time (verde)",
}


class Catalog:
    """
    EN: Indexed view over the public items JSON.
    ES: Vista indexada del items JSON publico.
    """

    def __init__(self, data, version=""):
        self.data = data
        self.version = version
        self.buildings = {
            str(x.get("wodID")): x for x in data.get("buildings", []) if x.get("wodID") is not None
        }
        self.units = {
            str(x.get("wodID")): x for x in data.get("units", []) if x.get("wodID") is not None
        }
        self.equipments = {}
        for x in data.get("equipments", []):
            key = x.get("id") or x.get("equipmentID")
            if key is not None:
                self.equipments[str(key)] = x
        self.carts = {}
        for x in data.get("shoppingCarts", []):
            key = str(x.get("typeID"))
            self.carts.setdefault(key, []).append(x)
        self.rewards = {
            str(x.get("rewardID")): x
            for x in data.get("rewards", [])
            if x.get("rewardID") is not None
        }

    # ------------------------------------------------------------------
    # EN: small resolvers / ES: resolvedores chicos
    # ------------------------------------------------------------------
    def unit_name(self, wod_id):
        unit = self.units.get(str(wod_id))
        if not unit:
            return f"unidad {wod_id}"
        name = unit.get("type") or unit.get("name") or f"unidad {wod_id}"
        role = unit.get("comment2") or unit.get("comment1") or ""
        return f"{name} ({role})" if role else name

    def equipment_name(self, equipment_id):
        item = self.equipments.get(str(equipment_id))
        if not item:
            return f"equipo {equipment_id}"
        return item.get("name") or item.get("comment1") or f"equipo {equipment_id}"

    def building(self, wod_id):
        return self.buildings.get(str(wod_id))

    def cart_entry(self, type_id):
        entries = self.carts.get(str(type_id))
        return entries[0] if entries else None

    def reward(self, reward_id):
        return self.rewards.get(str(reward_id))

    # ------------------------------------------------------------------
    # EN: cart effects / ES: efectos del carrito
    # ------------------------------------------------------------------
    def _reward_effects(self, reward):
        """
        EN: Reward dict -> readable effects string.
        ES: Dict de reward -> string de efectos legible.
        """
        if not reward:
            return "(sin datos)"
        parts = []
        for key, value in reward.items():
            if key in ("rewardID",) or key.startswith("ignore") or key.startswith("hidden"):
                continue
            if key == "units":
                for chunk in str(value).split(","):
                    if "+" not in chunk:
                        parts.append(f"{key} {chunk}")
                        continue
                    wid, amount = chunk.split("+", 1)
                    parts.append(f"{self._fmt(amount)}x {self.unit_name(wid)}")
                continue
            if key == "equipmentIDs":
                for eid in str(value).split(","):
                    parts.append(f"equipo {self.equipment_name(eid)}")
                continue
            label = EFFECT_LABELS.get(key)
            if label:
                parts.append(f"{self._fmt(value)}x {label}")
            else:
                parts.append(f"{key}={value}")
        return " · ".join(parts) if parts else "(sin efectos)"

    def _effect_numbers(self, reward):
        """
        EN: All numeric values of a reward (for variant matching).
        ES: Todos los valores numericos de un reward (para matchear variante).
        """
        nums = set()
        for key, value in (reward or {}).items():
            if key == "rewardID" or key.startswith("ignore") or key.startswith("hidden"):
                continue
            for n in re.findall(r"\d+", str(value)):
                nums.add(int(n))
        return nums

    def cart_effect(self, type_id):
        """
        EN: One cart option (typeID) as a readable string (default variant).
        ES: Una opcion de carrito (typeID) como string legible (variante default).
        """
        entry = self.cart_entry(type_id)
        if not entry:
            return f"TID {type_id} (sin mapear)"
        reward_id = entry.get("rewardID")
        return self._reward_effects(self.reward(reward_id))

    def cart_variant(self, type_ids, level=None, signal_numbers=None):
        """
        EN: Choose the shopping-cart variant (level band + lifetime-spent band)
            that best matches the numbers the cart dialog shows. The game picks
            that variant from the player's level/lifetime rubies, which we may
            not have; the dialog numbers are the reliable signal.
        ES: Elige la variante del carrito (banda de nivel + banda de gasto) que
            mejor coincide con los numeros que muestra el dialogo. El juego la
            elige segun nivel/gasto historico; los numeros del dialogo son la
            senal confiable.
        """
        tids = list(type_ids or [])
        if not tids:
            return None
        groups = collections.defaultdict(dict)
        for tid in tids:
            for entry in self.carts.get(str(tid), []):
                key = (
                    entry.get("minLevel"),
                    entry.get("maxLevel"),
                    entry.get("c2LifetimeSpentMin"),
                    entry.get("c2LifetimeSpentMax"),
                )
                groups[key].setdefault(tid, entry)

        candidates = []
        for key, entries in groups.items():
            if len(entries) < len(tids):
                continue
            if level is not None:
                try:
                    if not (int(key[0]) <= int(level) <= int(key[1])):
                        continue
                except Exception:
                    pass
            score = 0
            if signal_numbers:
                for tid in tids:
                    reward = self.reward(entries[tid].get("rewardID")) or {}
                    score += len(self._effect_numbers(reward) & set(signal_numbers))
            candidates.append((score, key, entries))

        if not candidates:
            return None

        candidates.sort(key=lambda item: (-item[0], str(item[1])))
        score, key, entries = candidates[0]
        sides = []
        for start in range(0, len(tids), 6):
            options = []
            for tid in tids[start:start + 6]:
                entry = entries[tid]
                options.append(self._reward_effects(self.reward(entry.get("rewardID"))))
            sides.append({"side": len(sides) + 1, "options": options})

        return {
            "group": key,
            "score": score,
            "sides": sides,
            "reward_ids": {str(t): entries[t].get("rewardID") for t in tids},
        }

    def cart_sides(self, type_ids):
        """
        EN: Split the TID list in 3 sides of 6 options (same as the game).
        ES: Divide la lista de TID en 3 lados de 6 opciones (igual que el juego).
        """
        tids = list(type_ids or [])
        sides = [tids[i:i + 6] for i in range(0, len(tids), 6)]
        return [{"side": n + 1, "options": [self.cart_effect(t) for t in side]}
                for n, side in enumerate(sides)]

    # ------------------------------------------------------------------
    # EN: events / ES: eventos
    # ------------------------------------------------------------------
    def format_event(self, event, base_time=None):
        """
        EN: Normalize one `sei` event into title/lines/end.
        ES: Normaliza un evento de `sei` en titulo/lineas/fin.
        """
        eid = event.get("EID")
        rs = int(event.get("RS") or 0)
        base = int(base_time or time.time())
        end = base + rs if rs else None
        out = {"eid": eid, "end": end, "raw": event, "lines": []}

        if eid == 7:
            content = event.get("WID") or event.get("OID") or event.get("TID")
            building = self.building(content) if content is not None else None
            discount = int(event.get("DIS") or 0)
            if building:
                name = building.get("name") or f"edificio {content}"
                level = building.get("level")
                cost = int(building.get("costC2") or 0)
                new_cost = round(cost * (1 - discount / 100.0)) if cost else 0
                out["title"] = f"Descuento en {name}"
                if level:
                    out["title"] += f" nivel {level}"
                if discount:
                    out["lines"].append(f"Descuento: {discount}%")
                if cost:
                    out["lines"].append(
                        f"Costo: {self._fmt(new_cost)} rubies (antes {self._fmt(cost)})"
                    )
            else:
                out["title"] = "Descuento de edificio"
                out["lines"].append(f"Contenido: {content} · descuento {discount}%")

        elif eid == 75:
            bid = event.get("BID")
            key = json.dumps(bid, separators=(",", ":"))
            name = BID_NAMES.get(key) or f"Oferta BID {key}"
            discount = int(event.get("DIS") or 0)
            out["title"] = name
            if discount:
                out["lines"].append(f"Descuento: {discount}%")

        elif eid == 90:
            tids = event.get("TID") or []
            out["title"] = "Carrito de compras"
            out["lines"].append(f"Costo: {self._fmt(event.get('C2'))} rubies")
            if event.get("LIM") is not None:
                out["lines"].append(f"Usos: {event.get('LIM')}")
            for side in self.cart_sides(tids):
                out["lines"].append(
                    f"Lado {side['side']}: " + " · ".join(side["options"])
                )

        elif eid in PRIME_TIME_EIDS:
            bonus = event.get("BONUS") or event.get("DIS") or event.get("content") or ""
            out["title"] = PRIME_TIME_EIDS[eid]
            if bonus:
                out["lines"].append(f"Bonus: {bonus}%")

        else:
            out["title"] = f"Evento EID {eid}"
            out["lines"].append(json.dumps(event, ensure_ascii=False)[:400])

        if end:
            out["lines"].append(f"Termina: {self._fmt_ts(end)}")
        return out

    def format_prime_time(self, poe, base_time=None):
        """
        EN: Format a `core_poe` frame (Prime Time bonus).
        ES: Formatea un frame `core_poe` (bonus Prime Time).
        """
        if not poe:
            return None
        bonus = poe.get("bonusPremium") or poe.get("bonusStandard") or 0
        remaining = int(poe.get("remainingTime") or 0)
        base = int(base_time or time.time())
        out = {
            "title": "Prime Time / Happy Hour",
            "bonus": bonus,
            "end": base + remaining if remaining else None,
            "lines": [],
        }
        if bonus:
            out["lines"].append(f"Bonus: +{bonus}%")
        if poe.get("discount"):
            out["lines"].append(f"Descuento: {poe.get('discount')}%")
        if out["end"]:
            out["lines"].append(f"Termina: {self._fmt_ts(out['end'])}")
        return out

    # ------------------------------------------------------------------
    # EN: helpers / ES: helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _fmt(value):
        try:
            f = float(value)
            if f.is_integer():
                return f"{int(f):,}".replace(",", ".")
            return f"{f:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            return str(value)

    @staticmethod
    def _fmt_ts(ts):
        try:
            return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ts)))
        except Exception:
            return str(ts)


def _fetch_version(timeout=15):
    response = requests.get(ITEMS_VERSION_URL, timeout=timeout)
    response.raise_for_status()
    text = response.text.strip()
    # EN: CastleItemXMLVersion=788.02 / ES: CastleItemXMLVersion=788.02
    return text.split("=", 1)[1].strip()


def load_catalog(force=False, verbose=True):
    """
    EN: Load the catalog from cache or download the current version.
    ES: Carga el catalogo desde cache o descarga la version actual.
    """
    version = _fetch_version()
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"items_v{version}.json")

    if force or not os.path.exists(path):
        if verbose:
            print(f"[i] Descargando items v{version}...", file=sys.stderr)
        tmp = path + ".tmp"
        url = ITEMS_URL.format(version=version)
        with requests.get(url, stream=True, timeout=120) as response:
            response.raise_for_status()
            with open(tmp, "wb") as handle:
                for chunk in response.iter_content(chunk_size=1 << 20):
                    handle.write(chunk)
        os.replace(tmp, path)
        if verbose:
            size_mb = os.path.getsize(path) / (1024 * 1024)
            print(f"[i] Items v{version} listo ({size_mb:.1f} MB).", file=sys.stderr)

    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return Catalog(data, version=version)


_CATALOG = None


def get_catalog(force=False, verbose=True):
    """
    EN: Process-wide catalog singleton.
    ES: Singleton del catalogo por proceso.
    """
    global _CATALOG
    if _CATALOG is None or force:
        _CATALOG = load_catalog(force=force, verbose=verbose)
    return _CATALOG
