# 4 · Garage add-on — vehicle history database

A small SQLite database with a web UI in the HA sidebar. Pure Python, no cloud, ~40 MB RAM. Stores:

- **Service log** — date, odometer, category, what was done, parts, cost, vendor, source
- **Components** — installed parts by system (suspension, brakes, batteries…): brand, part #, URL,
  purchased/installed dates, odometer at install, cost, condition; "on vehicle" miles computed live
- **Mods** — idea → planned → purchased → installed → dropped, with kit, URL, vendor, cost, priority
- **Inspections** — measurements (pad mm, rotor mm, resting volts, tread…) with a result. Brake / battery /
  suspension inspections advance the matching `_check` timers in HA automatically
- **Carfax import** — paste the report's *Detailed History* section; dates, mileage, vendor and service lines are
  parsed, categorized and previewed before import; one click sets the HA baselines from history
- CSV export of everything; JSON API for automations

## Install

1. Copy `addons/garage/` to `/addons/garage/` on the HA host (Samba share `addons`, or the SSH add-on).
2. Settings → Add-ons → Add-on Store → ⋮ → **Check for updates** → *Local add-ons* → Garage → Install → Start.
3. Configuration tab — set `vehicle_slug` to your generator slug (it's how the add-on knows which helpers to
   update and which To-do list to write). One add-on instance per vehicle; copy the folder with a different
   `slug:` in `config.yaml` for a second vehicle.
4. It appears in the sidebar as **Garage** and on the dashboard's Garage tab.

Back up `/share/garage/<slug>.db` — that file is the whole database.

## Sync with the dashboard

- Logging a service on the dashboard writes to the Garage (`rest_command.<slug>_garage_service`).
- Adding a component install, an inspection, or flipping a mod to *installed* in the Garage writes the service
  log and pushes the last date/odometer for that category into the HA helpers.
- `sensor.<slug>_garage_records` is an HA `rest` sensor polling the add-on every 10 min (counts, planned mods,
  spend, baselines as attributes).

## API

`GET /api/service_log | components | mods | inspections` · `GET /api/stats` · `POST /api/service_log`,
`/api/components`, `/api/mods`, `/api/inspections` (JSON, same fields as the forms) · `POST /api/sync` ·
`GET /export.csv`. Inside HA the add-on is `http://local-garage:8099`.

## Categories

Service-log categories double as the HA timer keys: `oil, fuel_filters, air_filter, tire_rotation, coolant,
trans_fluid, rear_diff, front_diff_tcase, brake_fluid, batteries, brake_check, battery_check, suspension_check`
plus informational ones (`tires, recall, inspection, mod, other`). Add your own in `server.py` → `CATEGORIES`;
anything in `HA_KEYS` is synced to `input_number.<slug>_<key>_last_miles` / `input_datetime.<slug>_<key>_last_date`.
