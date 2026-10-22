# 1 · Torque Pro → Home Assistant

## What you need

**Torque Pro (Android)** — [Google Play: Torque Pro (OBD 2 & Car)](https://play.google.com/store/apps/details?id=org.prowl.torque)
by Ian Hawkins. Get the **Pro** version (one-time purchase, a few dollars). Torque **Lite** is free but cannot
upload to a web server, which is the whole point here. There is no iOS version by this developer; see
"iPhone users" at the bottom, including a warning about a same-named app on the App Store.

**An OBD-II adapter.** Anything ELM327-compatible works with Torque. Rough guide:

| Type | Pros | Cons | Examples |
|---|---|---|---|
| Bluetooth Classic | cheapest, pairs like a headset | slowest; many clones | OBDLink LX/MX+, Veepeak OBDCheck BLE+, Vgate iCar Pro |
| Bluetooth LE | low power, iOS-friendly | Torque needs a BLE-capable build; check the adapter's Torque support | OBDLink CX, Veepeak BLE+ |
| Wi-Fi | fastest, most reliable with Torque | phone joins the dongle's AP (no internet unless the adapter supports station mode) | OBDLink MX Wi-Fi, WiCAN Pro |
| CAN-native | can also talk MQTT to HA *without* a phone | more setup | [MeatPi WiCAN Pro](https://www.meatpi.com/products/wican-pro) |

Avoid the $8 no-name ELM327 clones: they drop PIDs, fake protocol support, and sometimes keep the bus awake and
drain the battery. OBDLink and Veepeak are the usual safe picks; WiCAN Pro if you may want the phone-less MQTT
path later.

**HTTPS to your Home Assistant.** The phone uploads from wherever it is, so HA must be reachable from the
internet over TLS. Plain HTTP works only when the phone is on your LAN. Pick one:

| Option | Effort | Notes |
|---|---|---|
| **Home Assistant Cloud (Nabu Casa)** | none | Settings → Home Assistant Cloud → sign in → turn on *Remote control*. HA gives you a URL like `https://abc123xyz.ui.nabu.casa`. Nothing to open on your router, certificate handled for you, and the subscription funds HA development. Easiest by far |
| Cloudflare Tunnel | low | Free; the Cloudflared add-on + a domain you own. No inbound ports |
| Your own reverse proxy | medium | Nginx/Caddy/Traefik with a Let's Encrypt cert; DuckDNS + the Let's Encrypt add-on if you don't own a domain |

Throughout the docs the URL is written as `https://ha.example.com` — substitute yours. With Nabu Casa that's the
`*.ui.nabu.casa` address, used exactly the same way; the bearer token below is still required (Cloud only provides
the tunnel and certificate, not authentication for the API).

## Home Assistant side

Add the Torque platform to `configuration.yaml` and restart HA:

```yaml
sensor:
  - platform: torque
    name: Truck               # becomes the entity prefix: sensor.truck_engine_rpm ...
    email: you@example.com    # any string; Torque sends it with each upload to identify the vehicle
```

Use one entry per vehicle with a different `email` for each. The `name` must match the `slug` you'll put in the
generator's vehicle file (case doesn't matter; HA lowercases it).

Create a long-lived access token: your profile (bottom-left) → **Security** → *Long-lived access tokens* →
Create. Copy it; you'll paste it into Torque.

Confirm the endpoint exists: open `https://ha.example.com/api/torque` in a browser. **401 Unauthorized** means
it's there (you just didn't send a token). **404** means the platform didn't load — check the YAML.

## Torque side

Settings → **Data Logging & Upload**:

| Setting | Value |
|---|---|
| *Select what to log* | tick the PIDs you want uploaded (see step 2 for custom ones). Empty list = nothing is sent |
| *Web logging interval* | 10–30 s. The default 2 s floods your recorder for no benefit |
| *Only when OBD connected* | on |
| *Upload to web-server* | **on** — this is the master switch, separate from the URL |
| *Web-server URL* | `https://ha.example.com/api/torque` (no trailing slash) |
| *Send https: Bearer Token* | on, paste the token. Watch for a trailing space from the phone keyboard |
| *User Email Address* | exactly the `email:` string from the YAML |

Then Settings → **GPS / Location**: Torque holds every upload until it has a position fix. If you select
*external GPS* and don't have one, it waits forever. Leave it on the phone's GPS and grant Torque location
permission (Android settings → Apps → Torque → Permissions → Location → Allow).

Android battery settings: set Torque to **Unrestricted**, or Samsung/Pixel will freeze it in the background and
uploads stop when the screen is off.

**Adapter connection:** Settings → *OBD2 Adapter Settings* → connection type (Bluetooth / Wi-Fi) → choose the
device. Wi-Fi adapters usually live at `192.168.0.10:35000`; WiCAN is `192.168.80.1:3333` in AP mode.

## Test it

Start the vehicle, open Torque's realtime dashboard, wait a minute. In HA, Settings → Devices & services →
Entities, search your prefix: `sensor.truck_engine_rpm`, `sensor.truck_fuel_level_from_engine_ecu`, … appear as
soon as the first upload lands. Torque names them after its own PID labels; note the exact entity IDs — you'll
copy them into the vehicle file in step 3.

### If nothing shows up

- Simulate an upload from a PC (fill in token and email):
  `curl -H "Authorization: Bearer TOKEN" "https://ha.example.com/api/torque?eml=you@example.com&session=1&id=test&time=$(date +%s)000&userFullName0c=Engine%20RPM&userUnit0c=rpm&k0c=650"`
  `OK!` plus a new `sensor.truck_engine_rpm` = the server side is fine; the problem is in the app settings above.
- HA logs every rejected-token attempt (Settings → System → Logs, search `torque`). No entries at all = the phone
  isn't sending; entries with 401 = bad token.
- Torque sends nothing without a GPS fix and nothing unless *Upload to web-server* is ticked. Those two cause most
  "it never works" reports.

### iPhone users

Torque Pro is Android-only, by Ian Hawkins (Prowl). Home Assistant's Torque integration only understands its
upload format.

> **Beware the look-alike.** There is an App Store listing called
> [“Torque Pro : OBD2 Car Scanner”](https://apps.apple.com/us/app/torque-pro-obd2-car-scanner/id6504351894)
> by *Collabrains Technologies LTD*. It is not the same app or developer — it's a subscription scanner
> ($9.99/week) with ad tracking, and it has no web-upload feature. It **will not** send data to Home Assistant.
> Don't buy it for this.

Real iOS options:

- **WiCAN Pro (phone-less).** The dongle joins your Wi-Fi and publishes to HA's MQTT broker with auto-discovery —
  no app in the loop. Works while the vehicle is in Wi-Fi range (great for odometer and maintenance, not for
  live data on the road). Map the MQTT entity names in your vehicle file and the generated dashboard works the same.
- **A cheap Android device left in the vehicle** running Torque Pro on its own hotspot or a data SIM. Several people
  do this with an old phone; it's the only way to get Torque's full live upload with an iPhone in your pocket.
- iOS scanner apps (Car Scanner, OBD Fusion) are fine for reading codes and gauges but can't post to HA's endpoint.

### Keep the upload list lean

Torque will happily upload the phone's accelerometer, barometer and GPS-vs-OBD speed. Untick them. Every PID you
log becomes an HA entity with recorder history.
