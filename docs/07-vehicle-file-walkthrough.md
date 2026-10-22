# 7 · Walkthrough: from an empty HA to a working dashboard

A worked example for a **gas** vehicle with no custom PIDs yet; the diesel example is `vehicles/example-truck.yaml`.

### 1. Torque is uploading (doc 01)
`configuration.yaml`:
```yaml
sensor:
  - platform: torque
    name: Car
    email: tacoma@example.com
```
Restart, set up Torque with your HTTPS URL + token + that email, drive once. Settings → Entities, filter `car_`:
you'll see something like `sensor.car_engine_rpm`, `sensor.car_engine_coolant_temperature`,
`sensor.car_fuel_level_from_engine_ecu`, `sensor.car_voltage_control_module`, `sensor.car_run_time_since_engine_start`.

### 2. Prerequisites (doc 03)
packages enabled · `custom_templates/garage.jinja` copied · three Local To-do lists named
`car parts in stock`, `car parts to buy`, `car service history` · HACS `auto-entities` + `ha-shopping-list-improved`.

### 3. The vehicle file
```
cd generator && cp vehicles/example-car.yaml vehicles/tacoma.yaml
```
- `slug: car` (matches `name: Car` above)
- `torque:` paste the entity IDs from step 1; leave `""` for anything you don't see
- `items:` your manual's schedule. Keys are free-form except the `_check` ones that the Garage recognises
- `alerts:` only the ones whose inputs you have

### 4. Generate, install, restart
```
python3 gen.py vehicles/tacoma.yaml
cp out/car.yaml /config/packages/
```
Restart HA. Create the dashboard (Settings → Dashboards → Add → from scratch, URL `car`) → Raw configuration
editor → paste `out/car-dashboard.yaml`.

### 5. Baseline
Maintenance tab → set *Last done at / on* for each item from your records — or install the Garage add-on, paste
your Carfax report, and let it set them. Type the current odometer on the Overview tab (it stays manual until you
add an odometer PID).

### 6. Grow it
- Find your make's transmission-temp / odometer PIDs (doc 02), add them to Torque, put the entity IDs in the
  vehicle file, regenerate. The odometer then syncs itself.
- Set tire targets if you add TPMS PIDs and flip `tire_alerts: true`.
- Add vehicles by repeating with a new slug; one `garage.jinja` serves all of them.

### What the generator does with blanks
A blank Torque entry removes the card, gauge, graph row and alert that depend on it. `diesel: false` removes the
aftertreatment section, regen counter and DEF alert. Nothing references an entity you didn't provide, so a fresh
install has no "entity not found" tiles.
