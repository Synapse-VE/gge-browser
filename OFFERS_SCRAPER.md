# Offers scraper / Scraper de ofertas

EN: Read-only scraper for the in-game **Vista general de ofertas** panel. It
attaches to the Chrome instance that `main.py` already has open, reads the
offer slots/VOs, opens and closes the detail dialogs with real Selenium
clicks, and cross-references the `sei` events with the public items catalog.

ES: Scraper de solo lectura para el panel **Vista general de ofertas** del
juego. Se engancha al Chrome que ya abrio `main.py`, lee los slots/VO, abre y
cierra los dialogos de detalle con clicks reales de Selenium, y cruza los
eventos `sei` con el catalogo publico de items.

---

## Quick start / Uso rapido

```sh
# Chrome + main.py must be running and logged in.
.venv/bin/python offers_scraper.py              # panel + VOs
.venv/bin/python offers_scraper.py --details    # + dialogs (Selenium)
.venv/bin/python offers_scraper.py --events     # sei events
.venv/bin/python offers_scraper.py --json       # raw JSON
.venv/bin/python offers_scraper.py --watch 5    # new/closed offers
```

`--details` takes around a minute because it opens and closes each detail
dialog. `--watch` works without `--details` (it only compares the panel
signature, so it does not open anything).

---

## Files / Archivos

| File | Purpose |
|---|---|
| `offers_scraper.py` | Panel reader, VO extraction, dialog extraction, CLI |
| `gge_catalog.py` | Public items catalog + cart/building/unit formatters |
| `gge_events.py` | `sei` fetch via CDP hook, log fallback, player levels |
| `.gge-cache/` | Cached `items_v<version>.json` (~19 MB, gitignored) |

Dependencies: `selenium`, `requests`, `websocket-client` (already in
`requirements.txt`), plus Chrome with remote debugging on port `9222`.

---

## How it works / Como funciona

### 1. Panel detection

`offers_scraper.py` walks `window.uiStage` in the game iframe and finds the
container whose header is **Vista general de ofertas**. The panel exists in
the UI tree even while the hover tooltip is hidden, so no click or hover is
needed to read it.

Each visible slot exposes:

- `timer` (`txt_label`): the countdown shown in the panel.
- `status_class` / `inner_icon`: the offer type.
- `tooltip_id`: localization key used for the friendly name.
- `vos`: every offer VO attached to the slot (when the game exposes one).
- `global`: screen position of the slot (used by the Selenium click).

New or unknown offers are still listed; unknown tooltip/icon keys fall back
to the raw key.

### 2. VO content

Private offers expose a `PrivateOfferVO` (or a `GlobalOfferVO`) with:

- `id`, `endTimestamp`, `remainingSeconds`.
- `getTotalRewardListFromOfferVO()`: rewards (`_amount`, unit/equipment/currency).
- `getCostsForOfferAcception()`: costs.
- Event metadata (`_discount`, `_packageIDs`, `_eventType`).

This is read directly from the client memory: no dialog is opened for these
offers.

### 3. Detail dialogs (Selenium)

Offers without VO content (Prime Time, Prime Sales, event packages, the
shopping cart, ...) are opened with a trusted Selenium click:

1. Hover the offer-hub chest (bottom right) to show the panel.
2. Re-read the live slot hit center (the panel slides while opening).
3. Click the slot, wait for the dialog.
4. Read `txt_copy`, `txt_offer`, `txt_title`, `mc_costs`, `mc_old_costs`,
   `mc_percentOff`, `mc_time`, `mc_booster_container`, `mc_buildingClip`,
   `prime_sale_list`, `mc_package_container`.
5. Close with the real X (`btn_close`) or `hideFunction` for external
   preloaders; up to 3 retries with fresh coordinates.

Selenium attaches with `debugger_address=127.0.0.1:9222`; it does not launch
another browser. `driver.quit()` only closes the driver session, not Chrome.

### 4. Events (`sei`)

`gge_events.py` installs a passive WebSocket hook through CDP and sends:

```text
%xt%EmpireEx_25%sei%1%{}%
```

The hook captures the game socket on the next `pin`/`nch` (first run can wait
~30 s). The response is decoded (base64 `JXh0` or plain `%xt%...`) and parsed.
If the live socket is not available, the last `sei` frame in
`.gge-session.log` is used as fallback.

Known offer events:

| EID | Meaning |
|---|---|
| 7 | Building discount (`WID`, `DIS`) |
| 75 | Booster/Prime Sale (`BID`, `DIS`) |
| 90 | Shopping cart (`TID`, `C2`, `LIM`) |
| 997/998/999 | Prime Time (RE/Lacis/green) |

`core_poe` carries the Prime Time bonus (`bonusPremium`, `remainingTime`).

### 5. Items catalog

`gge_catalog.py` downloads the public
`items_v<version>.json` (version from `ItemsVersion.properties`) and indexes:

- `shoppingCarts` by `typeID`.
- `rewards` by `rewardID`.
- `buildings` by `wodID`.
- `units` by `wodID`.
- `equipments` by id.

It resolves cart options to readable effects (skips, units, mead, tickets,
equipment, ...) and building discounts to names/costs.

### 6. Cart variant

Each cart `typeID` has 12 variants: 3 level bands (13-69, 70-659, 660-1020)
by 4 lifetime-rubies-spent bands. The game selects one from the player's
account; the scraper does not know the lifetime spend, so it uses the numbers
shown in the cart dialog as the signal and scores every variant. The variant
with the most matches wins.

Example: current account selected `(660-1020, 600001-3000000)`, which matched
111 Pegasus tickets, 93/555/19/185/4 skips, 1.052 Mead units, 12.621 mead,
1.440/120/720/24/240/5 skips.

Prices displayed by the private offers are **C2 = rubies** (not coins);
`C1` is cash.

---

## Output / Salida

```
12) Especial de Halloween — ID 6370 · termina 2026-10-21 06:12
    Contenido:
      - 1x Equipo Skin (Unique, Skin unica 2009)
      - 1x Item de construccion (id 999)
      - 1x Item de construccion (id 864)
      - 1x Caja de botin
    Precio: 59.999 C2 (rubies)

 7) Oferta de marca / carrito
    Carrito: 30.000 rubies · 30 usos · termina 2026-10-20 19:36
      Lado 1: 111x tickets Pegaso · 93x saltos de 60 min · ...
      Lado 2: 1.052x MeadMace · ... · 12.621x aguamiel · 1x tickets ruleta
      Lado 3: 1.440x saltos de 5 min · ...
```

`--json` includes the raw `vos`, `detail`, `cart` and `prime` objects.

---

## Shop API (external webshop)

The blue shop opened by **¡Oferta! -> IR A LA TIENDA** is a separate web app
(`ef-canvas.public.ggs-ep.com`). It does **not** use the game WebSocket for
the catalogs; it uses HTTP + Bearer:

```http
GET https://api-ggs-canvas.public.ggs-ep.com/cashoffers/catalogs
    ?locale=es
    &category=cashoffers
    &sid=<SESSION_ID>
    &zoneId=212
    &criteria={"legendLevel":950,"level":70,"gamePlatform":["web"],
               "gameDistributionChannel":["goodgamestudios"],
               "storePaymentService":"ggs_payment",
               "storeIntegrationType":"embedded"}

Authorization: Bearer <JWT RS256, ~1092 chars>
Referer: https://ef-canvas.public.ggs-ep.com/
Accept: application/json, text/plain, */*
```

- No cookies; auth is the Bearer JWT (`iss: Empire`, `zoneId: 212`, ~24 h).
- CORS: preflight `OPTIONS 204`, `access-control-allow-origin: *`.
- Response: ~215 KB JSON with top-level `cashoffers`, `supersale`,
  `hcbundles`, `eventoffers`, `promos`, `hardCurrency`, `dailybundles`,
  `piggybank`, `growth-fund`, `subscriptions`.
- Counts observed: 53 cashoffers, 46 supersale, 19 eventoffers, 6 hcbundles,
  7 dailybundles, 3 subscriptions, 8 hardCurrency packs.
- Prices are in **cents** with `currencyCode` (e.g. `1999` = US$ 19.99).
- `hardCurrency.data.offers[]` has `hardCurrencyAmount`,
  `hardCurrencyOriginalAmount`, `hardCurrencyPercentageBonus`, `productIdMS`.
- `notifications-api/?types=...` returned `[]`.

The shop token/session is created when the shop is opened; synthetic clicks
on **IR A LA TIENDA** do not work (the game ignores them), so the shop is
opened manually. A future shop scraper can read the live shop session's
Bearer header (or the token from the shop iframe) and call the same endpoint.
The token is sensitive and must not be committed; `.shop-capture*.json` is
gitignored.

---

## Limitations / Limitaciones

- **GGS gift**: deliberately skipped. Its click claims the gift (a game
  action), so it is reported as "no se abre automatico".
- **Dialog flakiness**: if a click misses or a dialog does not close, the
  scraper retries; after 3 failed close attempts it stops with `[!]` instead
  of stacking dialogs. Repeat the run to fill any missing detail.
- **`--details` needs Selenium** and an open Chrome; it does not work in
  headless mode without the GUI session.
- **First events fetch** may wait up to ~30 s for the game socket; after the
  hook captures it, calls are immediate. `--events` can fall back to the last
  `sei` in the log (with its own timestamp).
- **Catalog cache**: first run downloads ~19 MB. Delete `.gge-cache/` to force
  a refresh after a game update.
- **Unknown layouts**: if a new offer dialog does not expose the named
  fields, the scraper falls back to the generic visible texts; the raw JSON
  keeps everything.
- **No purchases/claims**: the scraper only reads and opens/closes detail
  dialogs. It never clicks buy/claim/accept buttons.

---

## Security

- The session token/Bearer, `sid`, player ids and full captures are
  sensitive. Do not commit `.shop-capture*.json`, `.gge-*.png` or logs.
- The scraper does not store tokens by itself; it only reads the live page.
- Use it on your own account and at your own risk (GGE ToS).
