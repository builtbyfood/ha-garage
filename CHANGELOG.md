# Changelog

## 0.1.4 — 2026-10-22
- Add-on sources included: `addons/garage/server.py` (reads `HELPER_PREFIX`; `/api/stats`; ingress-safe URLs)
  and `addons/parts_intake/intake.py`. Repo is now complete and buildable.
- `addons/README.md` / `PORTING.md` trimmed to notes for forks.

## 0.1.3 — 2026-10-22
- docs/01: iOS section rewritten; warning about the unrelated "Torque Pro : OBD2 Car Scanner" App Store app
  (different publisher, subscription, no upload); real iOS routes (WiCAN MQTT, spare Android device).

## 0.1.2 — 2026-10-22
- Vehicle-neutral docs: 00-overview, 02 expanded to import / find / create PIDs with header table and Test
  procedure, 06-troubleshooting, 07 zero-to-dashboard walkthrough.
- `generator/vehicles/example-car.yaml` (gas, standard-PID-only) alongside the diesel example.

## 0.1.1 — 2026-10-22
- docs/01: remote-access table (Home Assistant Cloud / Nabu Casa, Cloudflare Tunnel, own reverse proxy).

## 0.1.0 — 2026-10-22
- First cut: vehicle-driven generator (`gen.py` + `garage.jinja`), generic Garage and Parts Intake add-on
  manifests, Ford 6.7L 2011–16 PID CSV, tutorials 01–05, MIT license.
