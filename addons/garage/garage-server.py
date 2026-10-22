#!/usr/bin/env python3
"""F-350 Garage — vehicle history database with a tiny web UI (stdlib only).

Tables
  service_log  what was done, when, at what mileage, by whom, what it cost (source: carfax|manual|ha)
  components   installed parts by system (suspension, brakes, batteries, steering, drivetrain, ...)
  mods         modification plan: idea -> planned -> purchased -> installed, with part/kit URL + cost
  inspections  measurements against a component (pad mm, battery volts/CCA, play, leaks ...)

Extras
  /import/carfax   paste a Carfax history -> parsed, categorized, previewed, imported
  /sync            push last-done date/odometer per maintenance category into HA helpers
  /api/*           JSON for anything else (HA rest sensors, scripts)
  /export.csv      everything as CSV
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import sqlite3
from datetime import datetime, date
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from contextvars import ContextVar

PREFIX: ContextVar[str] = ContextVar("prefix", default="")


def href(path: str) -> str:
    """Absolute URL under the ingress prefix: href('/mods') -> '/api/hassio_ingress/<t>/mods'."""
    return PREFIX.get() + (path if path.startswith('/') else '/' + path)

DB_PATH = Path(os.environ.get("DB_PATH", "/share/f350/garage.db"))
VEHICLE = os.environ.get("VEHICLE", "2016 Ford F-350 6.7L")
ODO_ENTITY = os.environ.get("ODOMETER_ENTITY", "input_number.f350_odometer")
HISTORY_TODO = os.environ.get("HISTORY_TODO", "todo.f_350_service_history")
HA_URL = os.environ.get("HA_URL", "http://supervisor/core").rstrip("/")
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
PORT = int(os.environ.get("PORT", "8099"))
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "info").upper(), format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("garage")

# ------------------------------------------------------------------ schema
SCHEMA = """
CREATE TABLE IF NOT EXISTS service_log (
  id INTEGER PRIMARY KEY, date TEXT NOT NULL, odometer INTEGER, category TEXT, description TEXT NOT NULL,
  parts TEXT, cost REAL, vendor TEXT, source TEXT DEFAULT 'manual', notes TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS components (
  id INTEGER PRIMARY KEY, system TEXT NOT NULL, name TEXT NOT NULL, position TEXT, brand TEXT, part_number TEXT, url TEXT,
  purchased_date TEXT, cost REAL, installed_date TEXT, installed_odo INTEGER,
  inspect_interval_mi INTEGER, inspect_interval_days INTEGER, condition TEXT, notes TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS mods (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT, status TEXT DEFAULT 'idea', part TEXT, url TEXT, vendor TEXT,
  cost REAL, purchased_date TEXT, installed_date TEXT, installed_odo INTEGER, priority INTEGER DEFAULT 3, notes TEXT,
  created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS inspections (
  id INTEGER PRIMARY KEY, date TEXT NOT NULL, odometer INTEGER, component_id INTEGER, system TEXT, item TEXT NOT NULL,
  measurement TEXT, unit TEXT, result TEXT, notes TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
"""

# maintenance categories <-> HA helper keys (must match the f350 package ITEMS keys)
CATEGORIES = {
    "oil":           ("Engine oil & filter",        ["oil and filter", "oil change", "oil changed", "lube, oil", "engine oil"]),
    "fuel_filters":  ("Fuel filters",               ["fuel filter"]),
    "air_filter":    ("Engine air filter",          ["air filter", "air cleaner"]),
    "tire_rotation": ("Tire rotation",              ["tire rotat", "tires rotated", "rotated"]),
    "ccv_filter":    ("CCV filter",                 ["crankcase", "ccv"]),
    "coolant":       ("Coolant flush",              ["coolant", "antifreeze", "cooling system flush"]),
    "trans_fluid":   ("Transmission fluid",         ["transmission fluid", "transmission serviced", "transmission flush"]),
    "rear_diff":     ("Rear differential fluid",     ["rear differential", "rear axle", "rear diff"]),
    "front_diff_tcase": ("Front diff / transfer case", ["front differential", "front axle", "transfer case", "front diff", "differential"]),
    "pre_filter":    ("Foam inlet pre-filter",       ["pre-filter", "prefilter", "foam filter", "inlet filter"]),
    "evap_clean":    ("Evaporator cleaning",        ["evaporator", "evap core"]),
    "brake_fluid":   ("Brake fluid",                ["brake fluid", "brake flush"]),
    "brakes":        ("Brake service (pads/rotors)", ["brake", "rotor", "pad"]),
    "batteries":     ("Battery replacement",        ["battery replaced", "batteries replaced", "new battery"]),
    "suspension":    ("Suspension / steering work", ["ball joint", "tie rod", "shock", "strut", "alignment", "suspension", "steering", "u-joint", "wheel bearing", "leaf spring", "track bar"]),
    "brake_check":   ("Brakes checked",             ["brake inspect", "brakes inspected", "brake check"]),
    "battery_check": ("Batteries checked",          ["battery test", "battery check", "battery inspected", "load test"]),
    "suspension_check": ("Suspension checked",      ["suspension inspect", "steering inspect", "front end inspect"]),
    "tires":         ("Tires",                      ["tire replaced", "tires replaced", "new tire", "tires mounted", "tire(s) replaced"]),
    "def":           ("DEF",                        ["diesel exhaust fluid", "def "]),
    "recall":        ("Recall / campaign",          ["recall", "campaign", "safety"]),
    "inspection":    ("Inspection",                 ["inspect", "multi-point", "emissions"]),
}
HA_KEYS = ["oil", "fuel_filters", "air_filter", "tire_rotation", "ccv_filter", "coolant", "trans_fluid", "rear_diff", "front_diff_tcase", "pre_filter", "evap_clean", "brake_fluid", "batteries", "brake_check", "battery_check", "suspension_check"]


def categorize(text: str) -> str:
    t = text.lower()
    # "checked"/"inspected" lines are inspections, never replacements
    if any(w in t for w in ("checked", "inspect", "tested")) and not any(w in t for w in ("replaced", "changed", "flushed", "rotated")):
        if "brake" in t:
            return "brake_check"
        if "battery" in t or "charging" in t:
            return "battery_check"
        if any(w in t for w in ("suspension", "steering", "front end", "ball joint", "tie rod")):
            return "suspension_check"
        return "inspection"
    for key, (_, kws) in CATEGORIES.items():
        if key == "brakes" and "brake fluid" in t:
            continue
        if any(k in t for k in kws):
            return key
    return "other"


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


# ------------------------------------------------------------------ Carfax parser
DATE_RX = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
MILES_RX = re.compile(r"\b(\d{1,3}(?:,\d{3})+|\d{4,6})\b")
NOISE = re.compile(r"(\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b|https?://\S+|www\.\S+|\.com\b)", re.I)


def parse_carfax(text: str) -> list[dict]:
    """Carfax copy/paste: blocks start with a date line, mileage usually on the same line,
    a vendor name follows, then one or more 'what was done' lines. Cells may be tab-separated.
    Returns editable records (one per service line)."""
    records: list[dict] = []
    cur: dict | None = None
    SKIP = {"vehicle serviced", "vehicle serviced.", "maintenance inspection completed", "comments", "source", "mileage", "date"}

    def is_noise(cell: str) -> bool:
        return bool(NOISE.search(cell) or re.fullmatch(r"[A-Za-z .'-]+,\s*[A-Z]{2}", cell) or cell.lower() in SKIP)

    for raw in text.splitlines():
        cells = [c.strip().strip("•-–* ") for c in raw.split("\t")]
        cells = [c for c in cells if c]
        if not cells:
            continue
        m = DATE_RX.match(cells[0])
        if m:
            if cur:
                records.append(cur)
            mm, dd, yy = m.groups()
            cur = {"date": f"{yy}-{int(mm):02d}-{int(dd):02d}", "odometer": None, "vendor": "", "lines": []}
            rest = [cells[0][m.end():].strip()] + cells[1:]
            for c in [c for c in rest if c]:
                if cur["odometer"] is None and re.fullmatch(r"\d{1,3}(?:,\d{3})+|\d+", c):
                    cur["odometer"] = int(c.replace(",", ""))
                elif is_noise(c):
                    continue
                elif not cur["vendor"] and len(c) < 60 and not c.lower().startswith(("vehicle", "oil", "tire", "brake", "fuel", "air", "battery")):
                    cur["vendor"] = c
                else:
                    cur["lines"].append(c)
            continue
        if cur is None:
            continue
        for c in cells:
            if is_noise(c):
                continue
            if not cur["vendor"] and not cur["lines"] and len(c) < 60 and not c.lower().startswith(("vehicle", "oil", "tire", "brake", "fuel", "air", "battery")):
                cur["vendor"] = c
            else:
                cur["lines"].append(c)
    if cur:
        records.append(cur)
    out = []
    for r in records:
        for ln in (r["lines"] or ["Vehicle serviced"]):
            out.append({"date": r["date"], "odometer": r["odometer"], "vendor": r["vendor"], "description": ln,
                        "category": categorize(ln), "source": "carfax"})
    return out


# ------------------------------------------------------------------ HA helpers
def ha(method: str, path: str, payload=None):
    if not TOKEN:
        return None
    try:
        r = requests.request(method, f"{HA_URL}/api/{path}", json=payload,
                             headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}, timeout=4)
        return r.json() if r.content else {}
    except Exception as e:  # noqa: BLE001
        log.warning("HA %s %s failed: %s", method, path, e)
        return None


def ha_state(entity: str):
    s = ha("GET", f"states/{entity}")
    return (s or {}).get("state")


def sync_to_ha(con) -> dict:
    """Push last-done per maintenance category into input_number/input_datetime helpers and a summary sensor."""
    done = {}
    for key in HA_KEYS:
        row = con.execute("SELECT date, odometer FROM service_log WHERE category=? ORDER BY date DESC, odometer DESC LIMIT 1", (key,)).fetchone()
        if not row:
            continue
        ha("POST", "services/input_datetime/set_datetime", {"entity_id": f"input_datetime.f350_{key}_last_date", "date": row["date"]})
        if row["odometer"]:
            ha("POST", "services/input_number/set_value", {"entity_id": f"input_number.f350_{key}_last_miles", "value": row["odometer"]})
        done[key] = {"date": row["date"], "odometer": row["odometer"]}
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("service_log", "components", "mods", "inspections")}
    # installs of mods/components are mirrored into service_log, so one sum covers everything
    spent = con.execute("SELECT COALESCE(SUM(cost),0) FROM service_log").fetchone()[0]
    planned = con.execute("SELECT COUNT(*) FROM mods WHERE status IN ('idea','planned')").fetchone()[0]
    if False:  # replaced by HA rest sensor polling /api/stats
      ha("POST", "states/sensor.f350_garage_records", {"state": counts["service_log"], "attributes": {
        "friendly_name": "F350 Garage Records", "icon": "mdi:garage", **counts, "total_spent": round(spent, 2),
        "mods_planned": planned, "last_sync": datetime.now().isoformat(timespec="seconds"), "baselines": done}})
    return {"baselines": done, "counts": counts, "total_spent": spent}


# ------------------------------------------------------------------ HTML
CSS = """
body{font-family:system-ui,sans-serif;margin:0;background:#111;color:#eee}
header{background:#1f2a33;padding:10px 16px;display:flex;gap:18px;align-items:center;flex-wrap:wrap}
header a{color:#8fd3ff;text-decoration:none;font-weight:600}header a.on{color:#fff;border-bottom:2px solid #fff}
main{padding:14px 16px;max-width:1300px}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid #333;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#1b1b1b;position:sticky;top:0}tr:hover td{background:#1a1a1a}
input,select,textarea{background:#222;color:#eee;border:1px solid #444;border-radius:4px;padding:6px;font:inherit}
input[type=number]{width:110px}input[type=date]{width:150px}
form.row{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;background:#181818;padding:12px;border-radius:8px;margin:12px 0}
form.row label{display:flex;flex-direction:column;font-size:12px;color:#aaa;gap:3px}
button{background:#2b7de9;color:#fff;border:0;border-radius:4px;padding:8px 14px;font-weight:600;cursor:pointer}
button.danger{background:#b3261e}button.ghost{background:#333}
.pill{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;background:#333}
.pill.installed{background:#1f6f3a}.pill.purchased{background:#7a5c00}.pill.planned{background:#2b4c7e}.pill.idea{background:#444}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin:10px 0}
.card{background:#181818;border-radius:8px;padding:12px}.card b{font-size:22px;display:block}
a.link{color:#8fd3ff}small{color:#999}
"""

NAV = [("Overview", "/"), ("Service log", "/service"), ("Components", "/components"), ("Mods", "/mods"),
       ("Inspections", "/inspections"), ("Import Carfax", "/import/carfax"), ("Export CSV", "/export.csv")]


def page(title: str, body: str, active: str = "/") -> str:
    nav = " ".join(f'<a href="{href(h)}" class="{"on" if h == active else ""}">{escape(n)}</a>' for n, h in NAV)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{escape(title)}</title><style>{CSS}</style></head>
<body><header><strong>🛻 {escape(VEHICLE)}</strong>{nav}</header><main>{body}</main></body></html>"""


def money(v):
    return f"${v:,.2f}" if v not in (None, "") else ""


def fmt_odo(v):
    try:
        return f"{int(float(v)):,}" if v not in (None, "") else ""
    except (TypeError, ValueError):
        return escape(str(v))


def form(action: str, fields: list[tuple], submit="Add") -> str:
    """fields: (name, label, type, extra) where extra is options list for select or default"""
    parts = []
    for name, label, typ, extra in fields:
        if typ == "select":
            opts = "".join(f'<option value="{escape(str(o))}">{escape(str(o))}</option>' for o in extra)
            parts.append(f"<label>{label}<select name='{name}'>{opts}</select></label>")
        elif typ == "textarea":
            parts.append(f"<label>{label}<textarea name='{name}' rows='2'></textarea></label>")
        else:
            val = f" value='{escape(str(extra))}'" if extra not in (None, "") else ""
            parts.append(f"<label>{label}<input name='{name}' type='{typ}'{val}></label>")
    return f"<form class='row' method='post' action='{href(action)}'>{''.join(parts)}<label>&nbsp;<button>{submit}</button></label></form>"


def table(rows, cols: list[tuple], delete_action: str | None = None) -> str:
    head = "".join(f"<th>{escape(c[0])}</th>" for c in cols) + ("<th></th>" if delete_action else "")
    body = []
    for r in rows:
        cells = []
        for _, key, fn in cols:
            v = r[key] if key in r.keys() else ""
            cells.append(f"<td>{fn(v) if fn else escape(str(v if v is not None else ''))}</td>")
        if delete_action:
            cells.append(f"<td><form method='post' action='{href(delete_action)}' onsubmit='return confirm(\"Delete?\")'>"
                         f"<input type='hidden' name='id' value='{r['id']}'><button class='danger'>✕</button></form></td>")
        body.append(f"<tr>{''.join(cells)}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body) or '<tr><td colspan=99><small>nothing yet</small></td></tr>'}</tbody></table>"


def linkify(url):
    return f"<a class='link' href='{escape(url)}' target='_blank'>link</a>" if url else ""


def pill(s):
    return f"<span class='pill {escape(s or '')}'>{escape(s or '')}</span>"


# ------------------------------------------------------------------ pages
def page_overview(con) -> str:
    odo = ha_state(ODO_ENTITY)
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("service_log", "components", "mods", "inspections")}
    spent = con.execute("SELECT COALESCE(SUM(cost),0) FROM service_log").fetchone()[0]
    mods_open = con.execute("SELECT COUNT(*) FROM mods WHERE status IN ('idea','planned','purchased')").fetchone()[0]
    last = con.execute("SELECT * FROM service_log ORDER BY date DESC, id DESC LIMIT 8").fetchall()
    per_cat = con.execute("SELECT category, MAX(date) d, COUNT(*) n FROM service_log GROUP BY category ORDER BY d DESC").fetchall()
    cards = f"""<div class='cards'>
      <div class='card'><small>Odometer (HA)</small><b>{fmt_odo(odo) if odo and odo.replace('.','',1).isdigit() else '—'}</b></div>
      <div class='card'><small>Service records</small><b>{counts['service_log']}</b></div>
      <div class='card'><small>Components tracked</small><b>{counts['components']}</b></div>
      <div class='card'><small>Open mods</small><b>{mods_open}</b></div>
      <div class='card'><small>Inspections</small><b>{counts['inspections']}</b></div>
      <div class='card'><small>Service spend logged</small><b>{money(spent)}</b></div></div>"""
    sync = f"<form method='post' action='{href('/sync')}'><button>Sync baselines → Home Assistant</button> <small>writes last-done date/mileage per category into the maintenance helpers</small></form>"
    cats = table(per_cat, [("Category", "category", lambda c: escape(CATEGORIES.get(c, (c,))[0]) if c in CATEGORIES else escape(str(c))),
                           ("Last", "d", None), ("Records", "n", None)])
    recent = table(last, [("Date", "date", None), ("Odo", "odometer", fmt_odo), ("Category", "category", None),
                          ("Done", "description", None), ("Vendor", "vendor", None), ("Cost", "cost", money)])
    return page("Garage", f"{cards}{sync}<h3>By category</h3>{cats}<h3>Recent</h3>{recent}", "/")


def page_service(con, q: dict) -> str:
    cat = q.get("category", [""])[0]
    rows = con.execute("SELECT * FROM service_log" + (" WHERE category=?" if cat else "") + " ORDER BY date DESC, odometer DESC, id DESC",
                       (cat,) if cat else ()).fetchall()
    f = form("/service/add", [("date", "Date", "date", date.today().isoformat()), ("odometer", "Odometer", "number", ha_state(ODO_ENTITY) or ""),
                              ("category", "Category", "select", list(CATEGORIES) + ["other"]), ("description", "What was done", "text", ""),
                              ("parts", "Parts", "text", ""), ("cost", "Cost $", "number", ""), ("vendor", "Vendor / shop", "text", ""),
                              ("notes", "Notes", "text", "")])
    filt = "<p>Filter: " + " ".join(f"<a class='link' href='{href('/service')}?category={k}'>{escape(v[0])}</a>" for k, v in CATEGORIES.items()) + f" <a class='link' href='{href('/service')}'>all</a></p>"
    t = table(rows, [("Date", "date", None), ("Odo", "odometer", fmt_odo), ("Category", "category", None), ("Done", "description", None),
                     ("Parts", "parts", None), ("Cost", "cost", money), ("Vendor", "vendor", None), ("Src", "source", None), ("Notes", "notes", None)],
              "/service/delete")
    return page("Service log", f"{f}{filt}{t}", "/service")


SYSTEMS = ["suspension", "steering", "brakes", "batteries", "drivetrain", "tires", "exhaust", "cooling", "fuel", "electrical", "body", "other"]
POSITIONS = ["", "LF", "RF", "LR", "RR",
             "LF+RF (front pair)", "LR+RR (rear pair)", "LF+LR (left side)", "RF+RR (right side)", "all 4",
             "front", "rear", "inner", "outer", "upper", "lower", "upper+lower"]


def page_components(con) -> str:
    rows = con.execute("SELECT * FROM components ORDER BY system, name, position").fetchall()
    f = form("/components/add", [("system", "System", "select", SYSTEMS), ("name", "Component", "text", ""), ("position", "Position", "select", POSITIONS),
                                 ("brand", "Brand", "text", ""), ("part_number", "Part #", "text", ""), ("url", "URL", "text", ""),
                                 ("purchased_date", "Purchased", "date", ""), ("cost", "Cost $", "number", ""),
                                 ("installed_date", "Installed", "date", ""), ("installed_odo", "Installed @ mi", "number", ""),
                                 ("inspect_interval_mi", "Inspect every mi", "number", "15000"), ("inspect_interval_days", "Inspect every days", "number", "365"),
                                 ("condition", "Condition", "select", ["unknown", "good", "fair", "worn", "replace soon", "failed"]), ("notes", "Notes", "text", "")])
    odo = ha_state(ODO_ENTITY)
    odo_i = int(float(odo)) if odo and odo.replace('.', '', 1).isdigit() else None

    def age(r):
        if r["installed_odo"] and odo_i:
            return f"{odo_i - int(r['installed_odo']):,} mi"
        return ""
    t = table(rows, [("System", "system", None), ("Component", "name", None), ("Pos", "position", None), ("Brand / part #", "brand", None),
                     ("#", "part_number", None), ("Link", "url", linkify), ("Installed", "installed_date", None), ("@ mi", "installed_odo", fmt_odo),
                     ("On truck", "installed_odo", lambda v, r=None: ""), ("Cost", "cost", money), ("Condition", "condition", pill), ("Notes", "notes", None)],
              "/components/delete")
    # cheap trick for the "On truck" column: recompute rows with age injected
    rows2 = [dict(r) | {"age": age(r)} for r in rows]
    t = table(rows2, [("System", "system", None), ("Component", "name", None), ("Pos", "position", None), ("Brand", "brand", None),
                      ("Part #", "part_number", None), ("Link", "url", linkify), ("Installed", "installed_date", None), ("@ mi", "installed_odo", fmt_odo),
                      ("On truck", "age", None), ("Cost", "cost", money), ("Condition", "condition", pill), ("Notes", "notes", None)],
               "/components/delete")
    tip = "<p><small>Suspension starter set for a 2011–16 Super Duty: shocks ×4, steering damper, track bar, ball joints (upper/lower ×2 each), tie-rod ends, drag link, U-joints, leaf-spring bushings, front hub/wheel bearings, sway-bar end links.</small></p>"
    return page("Components", f"{f}{tip}{t}", "/components")


MOD_STATUS = ["idea", "planned", "purchased", "installed", "dropped"]
MOD_CATS = ["suspension", "wheels/tires", "lighting", "electrical", "tune/engine", "exhaust", "towing", "interior", "exterior", "recovery", "storage", "audio/tech", "other"]


def page_mods(con) -> str:
    rows = con.execute("SELECT * FROM mods ORDER BY CASE status WHEN 'installed' THEN 3 WHEN 'dropped' THEN 4 WHEN 'purchased' THEN 1 WHEN 'planned' THEN 2 ELSE 0 END, priority, name").fetchall()
    f = form("/mods/add", [("name", "Mod", "text", ""), ("category", "Category", "select", MOD_CATS), ("status", "Status", "select", MOD_STATUS),
                           ("priority", "Priority 1-5", "number", "3"), ("part", "Part / kit", "text", ""), ("url", "URL", "text", ""), ("vendor", "Vendor", "text", ""),
                           ("cost", "Cost $", "number", ""), ("purchased_date", "Purchased", "date", ""), ("installed_date", "Installed", "date", ""),
                           ("installed_odo", "Installed @ mi", "number", ""), ("notes", "Notes / why", "text", "")])
    open_cost = con.execute("SELECT COALESCE(SUM(cost),0) FROM mods WHERE status IN ('idea','planned')").fetchone()[0]
    done_cost = con.execute("SELECT COALESCE(SUM(cost),0) FROM mods WHERE status IN ('purchased','installed')").fetchone()[0]
    summary = f"<p>Planned spend <b>{money(open_cost)}</b> · already spent <b>{money(done_cost)}</b></p>"
    rows2 = []
    for r in rows:
        d = dict(r)
        d["status_html"] = pill(r["status"])
        opts = "".join(f"<option {'selected' if s == r['status'] else ''}>{s}</option>" for s in MOD_STATUS)
        d["status_form"] = f"<form method='post' action='{href('/mods/status')}' style='display:inline'><input type='hidden' name='id' value='{r['id']}'><select name='status' onchange='this.form.submit()'>{opts}</select></form>"
        rows2.append(d)
    t = table(rows2, [("P", "priority", None), ("Mod", "name", None), ("Category", "category", None), ("Status", "status_form", lambda v: v),
                      ("Part / kit", "part", None), ("Link", "url", linkify), ("Vendor", "vendor", None), ("Cost", "cost", money),
                      ("Purchased", "purchased_date", None), ("Installed", "installed_date", None), ("@ mi", "installed_odo", fmt_odo), ("Notes", "notes", None)],
              "/mods/delete")
    return page("Mods", f"{f}{summary}{t}", "/mods")


INSPECT_ITEMS = ["brake pad thickness", "rotor thickness", "brake fluid moisture", "battery voltage (rest)", "battery CCA", "battery terminals",
                 "ball joint play", "tie rod play", "shock leak", "steering damper", "track bar", "U-joint", "wheel bearing", "leaf spring bushings",
                 "tire tread depth", "tire pressure", "coolant strength", "belt", "hoses", "DPF delta P (idle)", "other"]


def page_inspections(con) -> str:
    rows = con.execute("SELECT * FROM inspections ORDER BY date DESC, id DESC").fetchall()
    comps = con.execute("SELECT id, system, name, position FROM components ORDER BY system, name").fetchall()
    comp_opts = [""] + [f"{c['id']}: {c['system']} {c['name']} {c['position'] or ''}".strip() for c in comps]
    f = form("/inspections/add", [("date", "Date", "date", date.today().isoformat()), ("odometer", "Odometer", "number", ha_state(ODO_ENTITY) or ""),
                                  ("system", "System", "select", SYSTEMS), ("item", "Item", "select", INSPECT_ITEMS), ("component", "Component (optional)", "select", comp_opts),
                                  ("measurement", "Measurement", "text", ""), ("unit", "Unit", "select", ["", "mm", "in", "V", "A", "psi", "/32", "%", "°F"]),
                                  ("result", "Result", "select", ["ok", "watch", "replace soon", "replace now", "replaced"]), ("notes", "Notes", "text", "")])
    tip = ("<p><small>Rules of thumb: pads ≥ 4 mm ok, 3 mm watch, ≤ 2 mm replace · resting battery ≥ 12.6 V good, 12.4 fair, ≤ 12.2 replace soon · "
           "tread ≥ 6/32 ok, 4/32 watch, ≤ 3/32 replace · any ball-joint/tie-rod play = replace.</small></p>")
    t = table(rows, [("Date", "date", None), ("Odo", "odometer", fmt_odo), ("System", "system", None), ("Item", "item", None),
                     ("Measured", "measurement", None), ("Unit", "unit", None), ("Result", "result", pill), ("Notes", "notes", None)], "/inspections/delete")
    return page("Inspections", f"{f}{tip}{t}", "/inspections")


def page_import(preview: list[dict] | None = None, msg: str = "") -> str:
    txt = (f"<form method='post' action='{href('/import/carfax/preview')}'><p>Open your Carfax report, select the whole <em>Detailed History</em> section, copy, paste here. "
           "Dates, mileage, vendor and service lines are picked out and categorized; you can edit before importing.</p>"
           "<textarea name='text' rows='14' style='width:100%'></textarea><p><button>Preview</button></p></form>")
    if preview is None:
        return page("Import Carfax", msg + txt, "/import/carfax")
    rows = []
    for i, r in enumerate(preview):
        opts = "".join(f"<option {'selected' if k == r['category'] else ''}>{k}</option>" for k in list(CATEGORIES) + ["other"])
        rows.append(f"<tr><td><input type='checkbox' name='keep' value='{i}' checked></td>"
                    f"<td><input name='date_{i}' type='date' value='{r['date']}'></td>"
                    f"<td><input name='odo_{i}' type='number' value='{r['odometer'] or ''}'></td>"
                    f"<td><select name='cat_{i}'>{opts}</select></td>"
                    f"<td><input name='desc_{i}' value='{escape(r['description'])}' style='width:95%'></td>"
                    f"<td><input name='vendor_{i}' value='{escape(r['vendor'])}'></td></tr>")
    tbl = (f"<form method='post' action='{href('/import/carfax/commit')}'><table><thead><tr><th></th><th>Date</th><th>Odometer</th><th>Category</th><th>Description</th><th>Vendor</th></tr></thead>"
           f"<tbody>{''.join(rows)}</tbody></table><input type='hidden' name='n' value='{len(preview)}'><p><button>Import {len(preview)} records</button> "
           "<label><input type='checkbox' name='sync' checked> then sync baselines to Home Assistant</label></p></form>")
    return page("Import Carfax", f"<p>{len(preview)} records parsed.</p>{tbl}", "/import/carfax")


# ------------------------------------------------------------------ HTTP
def export_csv(con) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    for t in ("service_log", "components", "mods", "inspections"):
        rows = con.execute(f"SELECT * FROM {t}").fetchall()
        w.writerow([f"# {t}"])
        if rows:
            w.writerow(rows[0].keys())
            w.writerows([tuple(r) for r in rows])
        w.writerow([])
    return buf.getvalue().encode()


INGRESS_RX = re.compile(r"^/api/hassio_ingress/[^/]+")


def strip_ingress(path: str) -> str:
    """'/api/hassio_ingress/<token>/mods/add' -> '/mods/add'; bare root -> '/'."""
    p = INGRESS_RX.sub("", path).rstrip("/")
    return p or "/"


def num(v):
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        log.debug("%s " + fmt, self.address_string(), *a)

    def _send(self, body, ctype="text/html; charset=utf-8", code=200):
        data = body.encode() if isinstance(body, str) else body
        log.info("%s %s -> %s (prefix=%s)", self.command, strip_ingress(urlparse(self.path).path), code, PREFIX.get() or "-")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, path):
        log.info("%s %s -> 303 %s", self.command, strip_ingress(urlparse(self.path).path), path)
        self.send_response(303)
        self.send_header("Location", href(path))
        self.end_headers()

    def _form(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n).decode()
        if self.headers.get("Content-Type", "").startswith("application/json"):
            return json.loads(raw or "{}")
        return {k: v[0] if len(v) == 1 else v for k, v in parse_qs(raw, keep_blank_values=True).items()}

    # ---- GET
    def _set_prefix(self, raw_path: str) -> None:
        # Supervisor strips the ingress token from the path and tells us where we live via this header
        hdr = (self.headers.get("X-Ingress-Path") or "").rstrip("/")
        m = INGRESS_RX.match(raw_path)
        PREFIX.set(hdr or (m.group(0) if m else ""))

    def do_GET(self):
        u = urlparse(self.path)
        self._set_prefix(u.path)
        p = strip_ingress(u.path)
        q = parse_qs(u.query)
        con = db()
        try:
            if p == "/":
                return self._send(page_overview(con))
            if p == "/service":
                return self._send(page_service(con, q))
            if p == "/components":
                return self._send(page_components(con))
            if p == "/mods":
                return self._send(page_mods(con))
            if p == "/inspections":
                return self._send(page_inspections(con))
            if p == "/import/carfax":
                return self._send(page_import())
            if p == "/export.csv":
                return self._send(export_csv(con), "text/csv")
            if p.startswith("/api/"):
                t = p[5:]
                if t in ("service_log", "components", "mods", "inspections"):
                    return self._send(json.dumps([dict(r) for r in con.execute(f"SELECT * FROM {t} ORDER BY id DESC").fetchall()]), "application/json")
                if t == "stats":  # read-only, for HA's rest sensor
                    counts = {x: con.execute(f"SELECT COUNT(*) FROM {x}").fetchone()[0] for x in ("service_log", "components", "mods", "inspections")}
                    last = {}
                    for key in HA_KEYS:
                        row = con.execute("SELECT date, odometer FROM service_log WHERE category=? ORDER BY date DESC, odometer DESC LIMIT 1", (key,)).fetchone()
                        if row:
                            last[key] = {"date": row["date"], "odometer": row["odometer"]}
                    stats = {**counts,
                             "mods_planned": con.execute("SELECT COUNT(*) FROM mods WHERE status IN ('idea','planned')").fetchone()[0],
                             "total_spent": round(con.execute("SELECT COALESCE(SUM(cost),0) FROM service_log").fetchone()[0], 2),
                             "last_change": (con.execute("SELECT MAX(created) FROM service_log").fetchone()[0] or ""),
                             "baselines": last}
                    return self._send(json.dumps(stats), "application/json")
                if t == "summary":
                    return self._send(json.dumps(sync_to_ha(con)), "application/json")
            log.warning("no GET route for raw path %s", self.path)
            self._send("not found", code=404)
        finally:
            con.close()

    # ---- POST
    def do_POST(self):
        raw = urlparse(self.path).path
        self._set_prefix(raw)
        p = strip_ingress(raw)
        f = self._form()
        con = db()
        try:
            if p == "/service/add" or p == "/api/service_log":
                con.execute("INSERT INTO service_log(date,odometer,category,description,parts,cost,vendor,source,notes) VALUES(?,?,?,?,?,?,?,?,?)",
                            (f.get("date"), num(f.get("odometer")), f.get("category") or categorize(f.get("description", "")), f.get("description", ""),
                             f.get("parts"), num(f.get("cost")), f.get("vendor"), f.get("source", "manual"), f.get("notes")))
                con.commit()
                sync_to_ha(con)
                return self._send('{"ok":true}', "application/json") if p.startswith("/api") else self._redirect("/service")
            if p == "/service/delete":
                con.execute("DELETE FROM service_log WHERE id=?", (f["id"],)); con.commit(); return self._redirect("/service")
            if p == "/components/add" or p == "/api/components":
                con.execute("INSERT INTO components(system,name,position,brand,part_number,url,purchased_date,cost,installed_date,installed_odo,inspect_interval_mi,inspect_interval_days,condition,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (f.get("system"), f.get("name"), f.get("position"), f.get("brand"), f.get("part_number"), f.get("url"), f.get("purchased_date") or None,
                             num(f.get("cost")), f.get("installed_date") or None, num(f.get("installed_odo")), num(f.get("inspect_interval_mi")), num(f.get("inspect_interval_days")),
                             f.get("condition"), f.get("notes")))
                if f.get("installed_date"):
                    con.execute("INSERT INTO service_log(date,odometer,category,description,parts,cost,source) VALUES(?,?,?,?,?,?,'component')",
                                (f["installed_date"], num(f.get("installed_odo")), categorize(f.get("system", "") + " " + f.get("name", "")),
                                 f"Installed {f.get('name')} {f.get('position') or ''}".strip(), f"{f.get('brand') or ''} {f.get('part_number') or ''}".strip(), num(f.get("cost"))))
                con.commit(); sync_to_ha(con)
                return self._send('{"ok":true}', "application/json") if p.startswith("/api") else self._redirect("/components")
            if p == "/components/delete":
                con.execute("DELETE FROM components WHERE id=?", (f["id"],)); con.commit(); return self._redirect("/components")
            if p == "/mods/add" or p == "/api/mods":
                con.execute("INSERT INTO mods(name,category,status,priority,part,url,vendor,cost,purchased_date,installed_date,installed_odo,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                            (f.get("name"), f.get("category"), f.get("status"), num(f.get("priority")) or 3, f.get("part"), f.get("url"), f.get("vendor"), num(f.get("cost")),
                             f.get("purchased_date") or None, f.get("installed_date") or None, num(f.get("installed_odo")), f.get("notes")))
                con.commit(); sync_to_ha(con)
                return self._send('{"ok":true}', "application/json") if p.startswith("/api") else self._redirect("/mods")
            if p == "/mods/status":
                st = f.get("status")
                con.execute("UPDATE mods SET status=? WHERE id=?", (st, f["id"]))
                if st == "installed":
                    m = con.execute("SELECT * FROM mods WHERE id=?", (f["id"],)).fetchone()
                    odo = ha_state(ODO_ENTITY)
                    con.execute("UPDATE mods SET installed_date=COALESCE(installed_date,?), installed_odo=COALESCE(installed_odo,?) WHERE id=?",
                                (date.today().isoformat(), num(odo), f["id"]))
                    con.execute("INSERT INTO service_log(date,odometer,category,description,parts,cost,vendor,source) VALUES(?,?,?,?,?,?,?,'mod')",
                                (m["installed_date"] or date.today().isoformat(), m["installed_odo"] or num(odo), "mod", f"Installed mod: {m['name']}", m["part"], m["cost"], m["vendor"]))
                con.commit(); sync_to_ha(con); return self._redirect("/mods")
            if p == "/mods/delete":
                con.execute("DELETE FROM mods WHERE id=?", (f["id"],)); con.commit(); return self._redirect("/mods")
            if p == "/inspections/add" or p == "/api/inspections":
                comp = f.get("component") or ""
                cid = int(comp.split(":")[0]) if comp and comp[0].isdigit() else None
                con.execute("INSERT INTO inspections(date,odometer,component_id,system,item,measurement,unit,result,notes) VALUES(?,?,?,?,?,?,?,?,?)",
                            (f.get("date"), num(f.get("odometer")), cid, f.get("system"), f.get("item"), f.get("measurement"), f.get("unit"), f.get("result"), f.get("notes")))
                # an inspection counts as "checked" for the brakes/batteries/suspension maintenance timers
                cat = {"brakes": "brake_check", "batteries": "battery_check", "suspension": "suspension_check", "steering": "suspension_check"}.get(f.get("system"))
                if cat:
                    con.execute("INSERT INTO service_log(date,odometer,category,description,source) VALUES(?,?,?,?,'inspection')",
                                (f.get("date"), num(f.get("odometer")), cat, f"Inspected {f.get('item')}: {f.get('measurement') or ''}{f.get('unit') or ''} → {f.get('result')}"))
                if f.get("result") == "replaced" and f.get("system") in ("brakes", "batteries", "suspension", "steering"):
                    con.execute("INSERT INTO service_log(date,odometer,category,description,source) VALUES(?,?,?,?,'inspection')",
                                (f.get("date"), num(f.get("odometer")), {"steering": "suspension"}.get(f.get("system"), f.get("system")), f"Replaced {f.get('item')}"))
                if cid and f.get("result") in ("watch", "replace soon", "replace now"):
                    con.execute("UPDATE components SET condition=? WHERE id=?", ({"watch": "fair", "replace soon": "replace soon", "replace now": "failed"}[f["result"]], cid))
                con.commit(); sync_to_ha(con)
                return self._send('{"ok":true}', "application/json") if p.startswith("/api") else self._redirect("/inspections")
            if p == "/inspections/delete":
                con.execute("DELETE FROM inspections WHERE id=?", (f["id"],)); con.commit(); return self._redirect("/inspections")
            if p == "/import/carfax/preview":
                return self._send(page_import(parse_carfax(f.get("text", ""))))
            if p == "/import/carfax/commit":
                n = int(f.get("n", 0))
                keep = f.get("keep", [])
                keep = [keep] if isinstance(keep, str) else keep
                added = 0
                for i in map(int, keep):
                    con.execute("INSERT INTO service_log(date,odometer,category,description,vendor,source) VALUES(?,?,?,?,?,'carfax')",
                                (f.get(f"date_{i}"), num(f.get(f"odo_{i}")), f.get(f"cat_{i}"), f.get(f"desc_{i}"), f.get(f"vendor_{i}")))
                    added += 1
                con.commit()
                res = sync_to_ha(con) if f.get("sync") else {}
                msg = f"<p><b>Imported {added} records.</b> {'Baselines synced: ' + ', '.join(res.get('baselines', {})) if res else ''}</p>"
                return self._send(page_import(None, msg))
            if p == "/sync" or p == "/api/sync":
                res = sync_to_ha(con)
                return self._send(json.dumps(res), "application/json") if p.startswith("/api") else self._redirect("/")
            log.warning("no POST route for raw path %s (stripped: %s)", self.path, p)
            self._send("not found", code=404)
        finally:
            con.close()


if __name__ == "__main__":
    db().close()
    log.info("F-350 Garage listening on %s, db=%s", PORT, DB_PATH)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
