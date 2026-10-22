# ha-garage

![version](https://img.shields.io/badge/version-0.1.4-blue) · see [CHANGELOG.md](CHANGELOG.md)

Live OBD-II data, maintenance tracking and a vehicle history database in **Home Assistant** — for **any vehicle**
that Torque Pro can read, on any Bluetooth / Wi-Fi OBD-II dongle. Gas or diesel, one vehicle or several; each is
described in a short YAML file and the rest is generated. (It grew up on a 2016 Ford F-350 6.7L, which is why
that's the first PID file in the box.)

What you get:

| Piece | What it does |
|---|---|
| **Vehicle dashboard** | Live gauges and graphs from Torque, maintenance timers (miles *and* months), a "log a service" form, parts inventory with quantities and a barcode scanner, alerts to your phone |
| **Garage add-on** | A small database with a web UI: service log, installed components, mod plan with part links/cost, inspections with measurements, **Carfax paste import**, CSV export. Keeps the dashboard's timers in sync |
| **Parts Intake add-on** (optional) | Drop a photo of a part box into a media folder; it decodes the barcode / OCRs the part number locally and adds it to your "to buy" list. No cloud AI |
| **Generator** | One YAML file describes your vehicle; `gen.py` emits the HA package and dashboard with your prefix, names and intervals |

Everything runs on your own HA box. Only Torque's upload leaves the phone, and it goes straight to your HA URL.

## Quick start

0. **How it fits together** → [docs/00-overview.md](docs/00-overview.md)
1. **Phone + dongle + HTTPS** → [docs/01-torque-setup.md](docs/01-torque-setup.md)
2. **Custom PIDs** — import ours, or find and create your own → [docs/02-pid-import.md](docs/02-pid-import.md)
3. **Home Assistant package + dashboard** → [docs/03-home-assistant.md](docs/03-home-assistant.md)
4. **Garage add-on** (history database) → [docs/04-garage-addon.md](docs/04-garage-addon.md)
5. **Parts Intake add-on** (optional) → [docs/05-parts-intake-addon.md](docs/05-parts-intake-addon.md)
6. **Troubleshooting** → [docs/06-troubleshooting.md](docs/06-troubleshooting.md) · **Zero-to-dashboard walkthrough** → [docs/07-vehicle-file-walkthrough.md](docs/07-vehicle-file-walkthrough.md)

## Requirements

- Home Assistant OS or Supervised (the add-ons need the Supervisor). HA 2025.x or newer.
- An Android phone with **Torque Pro** by Ian Hawkins (the free Lite version cannot upload; the similarly named iOS app is unrelated and can't feed HA — see docs/01).
- An OBD-II adapter: any ELM327-compatible Bluetooth or Wi-Fi dongle. See the docs for picks.
- HTTPS access to your HA instance from the phone. **Home Assistant Cloud (Nabu Casa)** is the no-setup option — its `*.ui.nabu.casa` URL is all Torque needs; Cloudflare Tunnel or your own reverse proxy also work.
- HACS cards: `auto-entities`, `ha-shopping-list-improved`.

## Repo layout

```
generator/   gen.py + vehicles/example-truck.yaml (diesel) + vehicles/example-car.yaml (gas) + custom_templates/garage.jinja
pids/        Torque custom-PID CSVs (Ford 6.7L 2011-16 included; add yours via PR)
addons/      garage/ and parts_intake/ — local add-ons (copy to /addons/)
docs/        the tutorials
```

## Contributing a vehicle

Copy `generator/vehicles/example-truck.yaml`, fill in your Torque entity names and intervals, and if you
mapped custom PIDs add a CSV under `pids/` named `<make>_<engine>_<years>.csv`. PRs welcome.

## License

MIT
