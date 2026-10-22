#!/usr/bin/env python3
"""Generate a Home Assistant package + dashboard for one vehicle.

    python3 gen.py vehicles/example-truck.yaml

Writes  out/<slug>.yaml            -> copy to  /config/packages/<slug>.yaml
        out/<slug>-dashboard.yaml  -> paste into a new dashboard's Raw configuration editor
Needs   custom_templates/garage.jinja in /config/custom_templates/ (one copy serves all vehicles)
        three Local To-do lists named "<Name> Parts In Stock", "<Name> Parts To Buy", "<Name> Service History"
"""
import re, sys, pathlib, yaml

cfg = yaml.safe_load(open(sys.argv[1]))
P = cfg["slug"]                       # entity prefix
NAME = cfg["name"]
NAV = "/" + cfg.get("dashboard_url", P)
NOTIFY = cfg["notify"]
T = {k: (v or "") for k, v in cfg["torque"].items() if k != "tires"}
TIRES = [t for t in cfg["torque"].get("tires", []) if t]
DIESEL = bool(cfg.get("diesel"))
TIRE_ALERTS = bool(cfg.get("tire_alerts")) and len(TIRES) == 4
ITEMS = [tuple(i) for i in cfg["items"]]
LABEL = {k: l for k, l, *_ in ITEMS}
AL = cfg.get("alerts", {})
G = "http://local-garage:8099"   # the Garage add-on's Supervisor hostname


def slug(s):
    s = s.lower().replace("&", " ").replace("+", " ").replace("/", " ")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def todo(kind):
    # Local To-do lists must be created in the UI with these exact names: "<SLUG> parts in stock", etc.
    return "todo." + slug(f"{P} {kind}")


HIST = todo("service history"); STOCK = todo("parts in stock"); BUY = todo("parts to buy")
pct = lambda key: "sensor." + slug(f"{P} {LABEL[key]} Interval Used")

# ============================================================ package
pkg = {"input_number": {}, "input_datetime": {}, "input_select": {}, "input_text": {}, "input_boolean": {},
       "counter": {}, "template": [{"sensor": []}], "script": {}, "automation": [], "rest_command": {}, "sensor": []}
IN, ID = pkg["input_number"], pkg["input_datetime"]
num = lambda name, unit, mx=999999, step=1, icon="mdi:counter", mn=0: {"name": name, "min": mn, "max": mx, "step": step, "mode": "box", "unit_of_measurement": unit, "icon": icon}

IN[f"{P}_odometer"] = num(f"{P.upper()} Odometer", "mi")
IN[f"{P}_service_miles"] = num(f"{P.upper()} Service Miles (0 = use odometer)", "mi", icon="mdi:speedometer")
pkg["input_select"][f"{P}_service_item"] = {"name": f"{P.upper()} Service Item", "icon": "mdi:wrench", "options": [l for _, l, *_ in ITEMS]}
pkg["input_text"][f"{P}_service_notes"] = {"name": f"{P.upper()} Service Notes", "max": 255, "icon": "mdi:note-text"}
for key, lbl, mi, days, icon in ITEMS:
    IN[f"{P}_{key}_last_miles"] = num(f"{P.upper()} {lbl} Last Miles", "mi", icon=icon)
    ID[f"{P}_{key}_last_date"] = {"name": f"{P.upper()} {lbl} Last Date", "has_date": True, "has_time": False, "icon": "mdi:calendar-check"}
    pkg["template"][0]["sensor"].append({
        "name": f"{P.upper()} {lbl} Interval Used", "unique_id": f"{P}_{key}_interval_used", "unit_of_measurement": "%", "state_class": "measurement", "icon": icon,
        "state": "{% from 'garage.jinja' import interval_used %}" f"{{{{ interval_used('{P}', '{key}', {mi}, {days}) }}}}",
        "attributes": {"miles_interval": mi, "days_interval": days,
                       "miles_remaining": "{% from 'garage.jinja' import miles_remaining %}" f"{{{{ miles_remaining('{P}', '{key}', {mi}) }}}}",
                       "days_remaining": "{% from 'garage.jinja' import days_remaining %}" f"{{{{ days_remaining('{P}', '{key}', {days}) }}}}",
                       "last_miles": f"{{{{ states('input_number.{P}_{key}_last_miles')|int(0) }}}}",
                       "last_date": f"{{{{ states('input_datetime.{P}_{key}_last_date') }}}}"}})

BUNDLE = [(f, k) for f, k in (("rotation", "tire_rotation"), ("brake_check", "brake_check"), ("susp_check", "suspension_check"), ("batt_check", "battery_check")) if k in LABEL]
for flag, key in BUNDLE:
    pkg["input_boolean"][f"{P}_svc_also_{flag}"] = {"name": f"{P.upper()} Service also: {LABEL[key]}", "icon": "mdi:check"}

# engine hours
IN[f"{P}_engine_hours_base"] = num(f"{P.upper()} Engine Hours Base (completed runs, seconds)", "s", mx=999999999, icon="mdi:timer-sand")
IN[f"{P}_engine_hours_at_oil"] = num(f"{P.upper()} Engine Hours At Last Oil Change", "h", mx=99999, step=0.1, icon="mdi:oil")
pkg["template"][0]["sensor"] += [
  {"name": f"{P.upper()} Engine Hours", "unique_id": f"{P}_engine_hours", "unit_of_measurement": "h", "state_class": "total_increasing", "icon": "mdi:engine",
   "state": f"{{% set run = states('{T['run_time']}') %}}{{{{ ((states('input_number.{P}_engine_hours_base')|float(0) + (run|float(0) if is_number(run) else 0)) / 3600)|round(1) }}}}"},
  {"name": f"{P.upper()} Hours Since Oil Change", "unique_id": f"{P}_hours_since_oil", "unit_of_measurement": "h", "icon": "mdi:oil",
   "state": f"{{{{ (states('sensor.{P}_engine_hours')|float(0) - states('input_number.{P}_engine_hours_at_oil')|float(0))|round(1) }}}}"},
]
if TIRE_ALERTS:
    IN[f"{P}_tire_target_front"] = num(f"{P.upper()} Tire Pressure Target Front", "psi", mx=90, mn=20, icon="mdi:tire")
    IN[f"{P}_tire_target_rear"] = num(f"{P.upper()} Tire Pressure Target Rear", "psi", mx=90, mn=20, icon="mdi:tire")
    tl = "[" + ", ".join(f"states('{t}')|float(0)" for t in TIRES) + "]"
    av = "{{ " + " and ".join(f"is_number(states('{t}'))" for t in TIRES) + " }}"
    pkg["template"][0]["sensor"] += [
      {"name": f"{P.upper()} Tire Pressure Min", "unique_id": f"{P}_tire_pressure_min", "unit_of_measurement": "psi", "icon": "mdi:tire", "state_class": "measurement", "state": "{{ (" + tl + "|min)|round(1) }}", "availability": av},
      {"name": f"{P.upper()} Tire Pressure Spread", "unique_id": f"{P}_tire_pressure_spread", "unit_of_measurement": "psi", "icon": "mdi:arrow-expand-vertical", "state_class": "measurement", "state": "{% set t = " + tl + " %}{{ (t|max - t|min)|round(1) }}", "availability": av},
    ]
if DIESEL:
    pkg["counter"][f"{P}_regen_count"] = {"name": f"{P.upper()} DPF Regen Count", "icon": "mdi:fire", "step": 1, "restore": True}
    ID[f"{P}_last_regen"] = {"name": f"{P.upper()} Last DPF Regen", "has_date": True, "has_time": True, "icon": "mdi:fire-clock"}
    IN[f"{P}_odometer_at_last_regen"] = num(f"{P.upper()} Odometer At Last Regen", "mi", icon="mdi:fire")
    pkg["template"][0]["sensor"].append({"name": f"{P.upper()} Regen Interval Miles", "unique_id": f"{P}_regen_interval_miles", "unit_of_measurement": "mi", "icon": "mdi:map-marker-distance",
        "state": f"{{{{ (states('input_number.{P}_odometer')|float(0) - states('input_number.{P}_odometer_at_last_regen')|float(0))|round(0)|int }}}}",
        "availability": f"{{{{ states('input_number.{P}_odometer_at_last_regen')|float(0) > 0 }}}}"})
    egts = [T[k] for k in ("egt2", "egt3", "egt4") if T.get(k)]
    pkg["template"].append({"binary_sensor": [{"name": f"{P.upper()} DPF Regen Active", "unique_id": f"{P}_dpf_regen_active", "device_class": "heat", "icon": "mdi:fire",
        "state": "{% set t = [" + ", ".join(f"states('{e}')|float(0)" for e in egts) + "] %}{{ t|max > 950 }}", "delay_on": {"minutes": 2}, "delay_off": {"minutes": 3}}]})

pkg["sensor"] = [{"platform": "rest", "name": f"{P.upper()} Garage Records", "unique_id": f"{P}_garage_records", "icon": "mdi:garage",
                  "resource": f"{G}/api/stats", "scan_interval": 600, "timeout": 10, "value_template": "{{ value_json.service_log }}",
                  "json_attributes": ["components", "mods", "inspections", "mods_planned", "total_spent", "last_change", "baselines"]}]
rc = lambda path, payload: {"url": f"{G}{path}", "method": "post", "content_type": "application/json", "payload": payload}
pkg["rest_command"] = {
  f"{P}_garage_service": rc("/api/service_log", """{"date":"{{ date }}","odometer":{{ odometer|int(0) }},"category":"{{ category }}","description":"{{ description }}","parts":"{{ parts|default('') }}","cost":{{ cost|default(0) }},"vendor":"{{ vendor|default('') }}","notes":"{{ notes|default('') }}","source":"ha"}"""),
  f"{P}_garage_component": rc("/api/components", """{"system":"{{ system }}","name":"{{ name }}","position":"{{ position|default('') }}","brand":"{{ brand|default('') }}","part_number":"{{ part_number|default('') }}","url":"{{ url|default('') }}","installed_date":"{{ installed_date|default('') }}","installed_odo":{{ installed_odo|default(0) }},"cost":{{ cost|default(0) }},"condition":"{{ condition|default('good') }}","notes":"{{ notes|default('') }}"}"""),
  f"{P}_garage_mod": rc("/api/mods", """{"name":"{{ name }}","category":"{{ category|default('other') }}","status":"{{ status|default('idea') }}","priority":{{ priority|default(3) }},"part":"{{ part|default('') }}","url":"{{ url|default('') }}","vendor":"{{ vendor|default('') }}","cost":{{ cost|default(0) }},"notes":"{{ notes|default('') }}"}"""),
  f"{P}_garage_inspection": rc("/api/inspections", """{"date":"{{ date }}","odometer":{{ odometer|int(0) }},"system":"{{ system }}","item":"{{ item }}","measurement":"{{ measurement|default('') }}","unit":"{{ unit|default('') }}","result":"{{ result|default('ok') }}","notes":"{{ notes|default('') }}"}"""),
}


def stamp(key, garage_desc=None):
    seq = [{"action": "input_number.set_value", "target": {"entity_id": f"input_number.{P}_{key}_last_miles"}, "data": {"value": "{{ miles }}"}},
           {"action": "input_datetime.set_datetime", "target": {"entity_id": f"input_datetime.{P}_{key}_last_date"}, "data": {"date": "{{ now().date() }}"}}]
    if garage_desc:
        seq.append({"action": f"rest_command.{P}_garage_service", "continue_on_error": True, "data": {"date": "{{ now().date() }}", "odometer": "{{ miles }}", "category": key, "description": garage_desc, "notes": "bundled"}})
    return seq


choose = []
for key, lbl, *_ in ITEMS:
    seq = stamp(key)
    if key == "oil":
        seq.append({"action": "input_number.set_value", "target": {"entity_id": f"input_number.{P}_engine_hours_at_oil"}, "data": {"value": f"{{{{ states('sensor.{P}_engine_hours')|float(0) }}}}"}})
    choose.append({"conditions": [{"condition": "state", "entity_id": f"input_select.{P}_service_item", "state": lbl}], "sequence": seq})
pkg["script"][f"{P}_log_service"] = {
  "alias": f"{P.upper()} Log Service", "icon": "mdi:clipboard-check", "mode": "single",
  "variables": {"svc_miles": f"{{{{ states('input_number.{P}_service_miles')|int(0) }}}}",
                "miles": f"{{{{ svc_miles if svc_miles > 0 else states('input_number.{P}_odometer')|int(0) }}}}",
                "item": f"{{{{ states('input_select.{P}_service_item') }}}}", "notes": f"{{{{ states('input_text.{P}_service_notes') }}}}",
                "entry": "{{ now().strftime('%Y-%m-%d') }} · {{ item }} @ {{ '{:,}'.format(miles|int) }} mi"},
  "sequence": [
    {"choose": choose},
    {"action": f"rest_command.{P}_garage_service", "continue_on_error": True, "data": {"date": "{{ now().date() }}", "odometer": "{{ miles }}", "category": "{{ " + repr({l: k for k, l in LABEL.items()}) + "[item] }}", "description": "{{ item }}", "notes": "{{ notes }}"}},
    {"action": "input_number.set_value", "target": {"entity_id": f"input_number.{P}_odometer"}, "data": {"value": f"{{{{ [miles|int, states('input_number.{P}_odometer')|int(0)]|max }}}}"}},
    {"action": "todo.add_item", "target": {"entity_id": HIST}, "data": {"item": "{{ entry }}", "description": "{{ notes }}"}},
    {"action": "todo.update_item", "target": {"entity_id": HIST}, "data": {"item": "{{ entry }}", "status": "completed"}},
    {"action": "input_text.set_value", "target": {"entity_id": f"input_text.{P}_service_notes"}, "data": {"value": ""}},
    {"action": "input_number.set_value", "target": {"entity_id": f"input_number.{P}_service_miles"}, "data": {"value": 0}},
  ] + [{"if": [{"condition": "state", "entity_id": f"input_boolean.{P}_svc_also_{flag}", "state": "on"}],
        "then": stamp(key, "Done with service: " + LABEL[key]) + [{"action": "input_boolean.turn_off", "target": {"entity_id": f"input_boolean.{P}_svc_also_{flag}"}}]} for flag, key in BUNDLE],
}

# automations
pkg["automation"] = [
  {"id": f"{P}_odometer_sync", "alias": f"{P.upper()} Odometer Sync from Torque", "mode": "queued",
   "triggers": [{"trigger": "state", "entity_id": T["odometer"]}],
   "conditions": [{"condition": "template", "value_template": f"{{% set v = trigger.to_state.state %}}{{% set cur = states('input_number.{P}_odometer')|float(0) %}}{{{{ is_number(v) and v|float > cur and v|float < cur + 5000 }}}}"}],
   "actions": [{"action": "input_number.set_value", "target": {"entity_id": f"input_number.{P}_odometer"}, "data": {"value": "{{ trigger.to_state.state|float|round(0) }}"}}]},
  {"id": f"{P}_maintenance_due", "alias": f"{P.upper()} Maintenance Due Notification", "mode": "queued",
   "triggers": [{"trigger": "numeric_state", "entity_id": [pct(k) for k, *_ in ITEMS], "above": 100}],
   "actions": [{"action": NOTIFY, "data": {"title": f"{NAME}: service due", "message": "{{ trigger.to_state.name|replace(' Interval Used','') }} is at {{ trigger.to_state.state }}% of its interval.", "data": {"notification_icon": "mdi:wrench", "tag": P + "-{{ trigger.entity_id }}"}}}]},
  {"id": f"{P}_engine_hours", "alias": f"{P.upper()} Engine Hours Accumulate", "mode": "queued",
   "triggers": [{"trigger": "state", "entity_id": T["run_time"]}],
   "conditions": [{"condition": "template", "value_template": "{{ is_number(trigger.from_state.state) and is_number(trigger.to_state.state) and trigger.to_state.state|float < trigger.from_state.state|float and trigger.from_state.state|float > 30 }}"}],
   "actions": [{"action": "input_number.set_value", "target": {"entity_id": f"input_number.{P}_engine_hours_base"}, "data": {"value": f"{{{{ states('input_number.{P}_engine_hours_base')|float(0) + trigger.from_state.state|float }}}}"}}]},
]
trig, names = [], {}
def add(id_, name, t): trig.append({**t, "id": id_}); names[id_] = name
if T.get("trans_temp") and "trans_temp_high" in AL: add("trans", "Trans temp high", {"trigger": "numeric_state", "entity_id": T["trans_temp"], "above": AL["trans_temp_high"], "for": {"minutes": 2}})
if T.get("oil_temp") and "oil_temp_high" in AL: add("oil", "Oil temp high", {"trigger": "numeric_state", "entity_id": T["oil_temp"], "above": AL["oil_temp_high"], "for": {"minutes": 2}})
if T.get("egt1") and "egt1_high" in AL: add("egt", "EGT high", {"trigger": "numeric_state", "entity_id": T["egt1"], "above": AL["egt1_high"], "for": {"seconds": 30}})
if T.get("voltage") and "voltage_low" in AL: add("volts", "Battery voltage low", {"trigger": "numeric_state", "entity_id": T["voltage"], "below": AL["voltage_low"], "for": {"minutes": 5}})
if T.get("fuel_level") and "fuel_low_pct" in AL: add("fuel", "Fuel low", {"trigger": "numeric_state", "entity_id": T["fuel_level"], "below": AL["fuel_low_pct"]})
if DIESEL and T.get("def_level") and "def_low_pct" in AL: add("def", "DEF low", {"trigger": "numeric_state", "entity_id": T["def_level"], "below": AL["def_low_pct"]})
if TIRE_ALERTS:
    add("tire_f", "Front tire below target", {"trigger": "template", "value_template": f"{{{{ [states('{TIRES[0]}')|float(99), states('{TIRES[1]}')|float(99)]|min < states('input_number.{P}_tire_target_front')|float(0) - 5 }}}}", "for": {"minutes": 2}})
    add("tire_r", "Rear tire below target", {"trigger": "template", "value_template": f"{{{{ [states('{TIRES[2]}')|float(99), states('{TIRES[3]}')|float(99)]|min < states('input_number.{P}_tire_target_rear')|float(0) - 5 }}}}", "for": {"minutes": 2}})
    add("tire_spread", "One tire low vs the others", {"trigger": "numeric_state", "entity_id": f"sensor.{P}_tire_pressure_spread", "above": AL.get("tire_spread_psi", 6), "for": {"minutes": 2}})
if trig:
    pkg["automation"].append({"id": f"{P}_alerts", "alias": f"{P.upper()} Alerts", "mode": "queued", "triggers": trig,
        "actions": [{"action": NOTIFY, "data": {"title": f"{NAME}: " + "{{ " + repr(names) + "[trigger.id] }}",
                     "message": "{{ trigger.to_state.name if trigger.to_state is defined else '' }} {{ trigger.to_state.state if trigger.to_state is defined else '' }}", "data": {"tag": P + "-alert-{{ trigger.id }}"}}}]})
if DIESEL and T.get("dpf_soot"):
    pkg["automation"].append({"id": f"{P}_regen_counter", "alias": f"{P.upper()} DPF Regen Counter", "mode": "single",
      "triggers": [{"trigger": "state", "entity_id": f"binary_sensor.{P}_dpf_regen_active", "from": "off", "to": "on", "id": "egt"},
                   {"trigger": "state", "entity_id": T["dpf_soot"], "id": "soot"}],
      "conditions": [{"condition": "template", "value_template": "{{ trigger.id == 'egt' or (is_number(trigger.from_state.state) and is_number(trigger.to_state.state) and trigger.from_state.state|float - trigger.to_state.state|float > 25) }}"}],
      "actions": [{"action": "counter.increment", "target": {"entity_id": f"counter.{P}_regen_count"}},
                  {"action": "input_datetime.set_datetime", "target": {"entity_id": f"input_datetime.{P}_last_regen"}, "data": {"datetime": "{{ now().strftime('%Y-%m-%d %H:%M:%S') }}"}},
                  {"action": "input_number.set_value", "target": {"entity_id": f"input_number.{P}_odometer_at_last_regen"}, "data": {"value": f"{{{{ states('input_number.{P}_odometer')|float(0) }}}}"}},
                  {"action": NOTIFY, "data": {"title": f"{NAME}: DPF regen", "message": "Soot " + f"{{{{ states('{T['dpf_soot']}')|round(0) }}}}" + "%.", "data": {"tag": P + "-regen"}}}]})

out = pathlib.Path("out"); out.mkdir(exist_ok=True)
with open(out / f"{P}.yaml", "w") as f:
    f.write(f"# {NAME} — generated by ha-garage gen.py. Copy to /config/packages/{P}.yaml\n")
    yaml.safe_dump(pkg, f, sort_keys=False, allow_unicode=True, width=200)

# ============================================================ dashboard
OK, WARN, BAD = "var(--success-color)", "var(--warning-color)", "var(--error-color)"
Gs = lambda *pts: [{"from": a, "color": c} for a, c in pts]
gauge = lambda e, n, mn, mx, segs: {"type": "gauge", "entity": e, "name": n, "min": mn, "max": mx, "needle": True, "segments": segs}
ent = lambda e, n: {"entity": e, "name": n}
live = [(T[k], n) for k, n in (("odometer", "Odometer (ECU)"), ("rpm", "RPM"), ("coolant_temp", "Coolant"), ("oil_temp", "Oil temp"), ("trans_temp", "Trans temp"),
                                ("boost", "Boost"), ("map", "MAP"), ("fuel_level", "Fuel"), ("def_level", "DEF"), ("mpg_long", "MPG"), ("voltage", "Voltage"), ("ambient", "Ambient"),
                                ("engine_load", "Load"), ("fuel_rate", "Fuel rate")) if T.get(k)] + [(t, "Tire " + t[-2:].upper()) for t in TIRES] + [(f"sensor.{P}_engine_hours", "Engine hours")]
overview = {"title": "Overview", "path": "overview", "icon": "mdi:view-dashboard", "type": "sections", "max_columns": 3, "sections": [
  {"type": "grid", "cards": [{"type": "heading", "heading": NAME, "heading_style": "title", "icon": "mdi:car"},
    {"type": "tile", "entity": f"input_number.{P}_odometer", "name": "Odometer", "icon": "mdi:counter", "features": [{"type": "numeric-input", "style": "buttons"}]},
    {"type": "button", "name": "Log a service", "icon": "mdi:clipboard-check", "tap_action": {"action": "navigate", "navigation_path": f"{NAV}/maintenance"}}]},
  {"type": "grid", "cards": [{"type": "heading", "heading": "Due / coming up (≥85%)", "heading_style": "title", "icon": "mdi:alert-circle"},
    {"type": "custom:auto-entities", "card": {"type": "entities", "state_color": True}, "show_empty": True,
     "filter": {"template": "{% set ns = namespace(items=[]) %}{% for s in states.sensor if s.entity_id is match('sensor\\\\." + P + "_.*_interval_used$') and is_number(s.state) and s.state|float >= 85 %}"
                            "{% set ns.items = ns.items + [{'entity': s.entity_id, 'name': s.name|replace('" + P.upper() + " ','')|replace(' Interval Used',''), 'icon': s.attributes.icon}] %}{% endfor %}{{ ns.items | to_json }}"},
     "sort": {"method": "state", "numeric": True, "reverse": True}},
    {"type": "markdown", "content": "≥100% is past its interval; 85–99% is coming up."}]},
  {"type": "grid", "column_span": 3, "cards": [{"type": "heading", "heading": "Live · Torque", "heading_style": "title", "icon": "mdi:engine"}] +
     [{"type": "entities", "state_color": True, "entities": [ent(e, n) for e, n in live[i:i + 6]]} for i in range(0, len(live), 6)]},
]}
glance = [gauge(T["fuel_level"], "Fuel", 0, 100, Gs((0, BAD), (15, WARN), (30, OK)))] if T.get("fuel_level") else []
if T.get("voltage"): glance.append(gauge(T["voltage"], "Battery", 10, 16, Gs((10, BAD), (12.2, WARN), (13.2, OK), (15, BAD))))
if T.get("trans_temp"): glance.append(gauge(T["trans_temp"], "Trans temp", 100, 300, Gs((100, OK), (210, WARN), (240, BAD))))
if DIESEL and T.get("dpf_soot"): glance.append(gauge(T["dpf_soot"], "DPF soot", 0, 120, Gs((0, OK), (70, WARN), (100, BAD))))
if TIRE_ALERTS: glance.append(gauge(f"sensor.{P}_tire_pressure_min", "Lowest tire", 20, 90, Gs((20, BAD), (40, WARN), (50, OK))))
overview["sections"].insert(2, {"type": "grid", "column_span": 3, "cards": [{"type": "heading", "heading": "At a glance", "heading_style": "title", "icon": "mdi:eye"}] + glance})

diag_sections = []
if DIESEL:
    diag_sections.append({"type": "grid", "cards": [{"type": "heading", "heading": "Aftertreatment (DPF / SCR)", "heading_style": "title", "icon": "mdi:smog"},
      {"type": "tile", "entity": f"binary_sensor.{P}_dpf_regen_active", "name": "DPF regen in progress", "icon": "mdi:fire", "color": "orange"},
      {"type": "entities", "entities": [ent(f"counter.{P}_regen_count", "Regens counted"), ent(f"input_datetime.{P}_last_regen", "Last regen"), ent(f"sensor.{P}_regen_interval_miles", "Miles since last regen")]}]
      + ([gauge(T["dpf_soot"], "DPF soot load", 0, 120, Gs((0, OK), (70, WARN), (100, BAD)))] if T.get("dpf_soot") else [])
      + ([gauge(T["dpf_delta_p"], "DPF delta pressure (idle)", 0, 60, Gs((0, OK), (25, WARN), (40, BAD)))] if T.get("dpf_delta_p") else [])
      + [{"type": "history-graph", "title": "Exhaust temps (24h)", "hours_to_show": 24, "entities": [ent(T[k], k.upper()) for k in ("egt1", "egt2", "egt3", "egt4") if T.get(k)]}]})
diag_sections.append({"type": "grid", "cards": [{"type": "heading", "heading": "Engine & drivetrain", "heading_style": "title", "icon": "mdi:engine"}]
  + ([gauge(T["oil_temp"], "Oil temp", 100, 300, Gs((100, OK), (230, WARN), (260, BAD)))] if T.get("oil_temp") else [])
  + ([gauge(T["coolant_temp"], "Coolant", 100, 260, Gs((100, OK), (220, WARN), (240, BAD)))] if T.get("coolant_temp") else [])
  + ([gauge(T["boost"], "Boost", -15, 40, Gs((-15, OK), (30, WARN), (36, BAD)))] if T.get("boost") else [])
  + [{"type": "history-graph", "title": "Load & boost (6h)", "hours_to_show": 6, "entities": [ent(T[k], k) for k in ("engine_load", "boost") if T.get(k)]}]})
diag_sections.append({"type": "grid", "cards": [{"type": "heading", "heading": "Fuel, electrical & tires", "heading_style": "title", "icon": "mdi:gas-station"}]
  + ([{"type": "entities", "title": "Tires", "entities": [ent(f"input_number.{P}_tire_target_front", "Target front"), ent(f"input_number.{P}_tire_target_rear", "Target rear"), ent(f"sensor.{P}_tire_pressure_min", "Lowest tire"), ent(f"sensor.{P}_tire_pressure_spread", "Spread")]},
      {"type": "history-graph", "title": "Tire pressures (7d)", "hours_to_show": 168, "entities": [ent(t, t[-2:].upper()) for t in TIRES]}] if TIRE_ALERTS else [])
  + [{"type": "entities", "entities": [ent(x, n) for x, n in ((T.get("fuel_rate"), "Fuel rate"), (T.get("mpg_long"), "MPG long-term"), (T.get("run_time"), "Run time this start"), (f"sensor.{P}_engine_hours", "Engine hours"), (f"sensor.{P}_hours_since_oil_change", "Hours since oil change"), (T.get("ambient"), "Ambient")) if x]}]})
diag = {"title": "Diagnostics", "path": "diag", "icon": "mdi:stethoscope", "type": "sections", "max_columns": 3, "sections": diag_sections}

record = {"type": "grid", "column_span": 2, "cards": [{"type": "heading", "heading": "Record a service", "heading_style": "title"},
  {"type": "entities", "entities": [ent(f"input_select.{P}_service_item", "What was done"), ent(f"input_number.{P}_service_miles", "Mileage (0 = current odometer)"), ent(f"input_text.{P}_service_notes", "Notes")]
                        + ([{"type": "section", "label": "Also done at the same time"}] + [ent(f"input_boolean.{P}_svc_also_{f}", LABEL[k]) for f, k in BUNDLE] if BUNDLE else [])},
  {"type": "button", "name": "Save to history", "icon": "mdi:content-save", "show_state": False, "tap_action": {"action": "perform-action", "perform_action": f"script.{P}_log_service", "confirmation": {"text": "Log this service?"}}}]}
maint = [record]
for key, lbl, mi, days, icon in ITEMS:
    iv = " / ".join(x for x in ([f"{mi:,} mi" if mi else ""] + [f"{days // 30} mo" if days else ""]) if x)
    maint.append({"type": "grid", "cards": [{"type": "heading", "heading": lbl, "heading_style": "subtitle", "icon": icon, "badges": [{"type": "entity", "entity": pct(key)}]},
        gauge(pct(key), f"Interval: {iv}", 0, 120, Gs((0, OK), (85, WARN), (100, BAD))),
        {"type": "entities", "entities": [ent(f"input_number.{P}_{key}_last_miles", "Last done at"), ent(f"input_datetime.{P}_{key}_last_date", "Last done on"),
            {"type": "attribute", "entity": pct(key), "attribute": "miles_remaining", "name": "Miles remaining", "suffix": "mi"},
            {"type": "attribute", "entity": pct(key), "attribute": "days_remaining", "name": "Days remaining"}]}]})
maint.append({"type": "grid", "column_span": 2, "cards": [{"type": "heading", "heading": "Service history", "heading_style": "title", "icon": "mdi:history"}, {"type": "todo-list", "entity": HIST, "title": "Completed services"}]})
maintenance = {"title": "Maintenance", "path": "maintenance", "icon": "mdi:wrench", "type": "sections", "max_columns": 4, "sections": maint}

parts = {"title": "Parts", "path": "parts", "icon": "mdi:package-variant", "type": "sections", "max_columns": 2, "sections": [
  {"type": "grid", "cards": [{"type": "heading", "heading": "In stock", "heading_style": "title", "icon": "mdi:package-variant-closed"},
    {"type": "custom:ha-shopping-list-improved", "entity": STOCK, "title": "On the shelf", "mode": "shopping", "quantity": "beginning", "show_plus_minus": True, "show_quantity_box": True, "show_qrscan_button": True}]},
  {"type": "grid", "cards": [{"type": "heading", "heading": "To buy", "heading_style": "title", "icon": "mdi:cart"},
    {"type": "custom:ha-shopping-list-improved", "entity": BUY, "title": "Order list", "mode": "shopping", "quantity": "beginning", "show_plus_minus": True, "show_quantity_box": True, "show_qrscan_button": True, "show_clear_button": True}]},
]}
garage = {"title": "Garage", "path": "garage", "icon": "mdi:garage", "type": "sections", "max_columns": 2, "sections": [{"type": "grid", "cards": [
  {"type": "heading", "heading": "History database", "heading_style": "title", "icon": "mdi:database"},
  {"type": "button", "name": "Open Garage", "icon": "mdi:garage-open", "tap_action": {"action": "navigate", "navigation_path": "/hassio/ingress/local_garage"}},
  {"type": "entities", "entities": [ent(f"sensor.{P}_garage_records", "Service records")] + [{"type": "attribute", "entity": f"sensor.{P}_garage_records", "attribute": a, "name": n} for a, n in (("components", "Components"), ("mods", "Mods"), ("mods_planned", "Mods planned"), ("inspections", "Inspections"), ("total_spent", "Spend logged"), ("last_change", "Last change"))]}]}]}

with open(out / f"{P}-dashboard.yaml", "w") as f:
    f.write(f"# {NAME} dashboard — paste into Settings > Dashboards > (new dashboard, url '{cfg.get('dashboard_url', P)}') > Raw configuration editor\n")
    yaml.safe_dump({"title": NAME, "views": [overview, diag, maintenance, parts, garage]}, f, sort_keys=False, allow_unicode=True, width=120)
print(f"wrote out/{P}.yaml and out/{P}-dashboard.yaml  (to-do lists expected: {STOCK}, {BUY}, {HIST})")
