# 3 · Home Assistant: package + dashboard

The generator turns one vehicle description into everything HA needs. You don't hand-edit 1,000 lines of YAML;
you edit a 60-line vehicle file and regenerate.

## One-time prerequisites

1. **Packages enabled** in `configuration.yaml`:
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
2. **Jinja macros**: copy `generator/custom_templates/garage.jinja` to `/config/custom_templates/garage.jinja`
   (create the folder). One copy serves every vehicle.
3. **Three Local To-do lists** per vehicle: Settings → Devices & services → Add integration → *Local To-do*,
   named `<slug> parts in stock`, `<slug> parts to buy`, `<slug> service history` (e.g. `truck parts in stock`).
   The generator prints the entity IDs it expects.
4. **HACS cards**: `auto-entities` (Due list) and `ha-shopping-list-improved` (parts lists with quantities and a
   camera barcode scanner). Install both from HACS → Frontend.
5. The **Garage add-on** (next doc) — the package includes a `rest` sensor and four `rest_command`s that talk to it.
   HA tolerates them being unreachable until it's installed.

## Describe your vehicle

```
cd generator
cp vehicles/example-truck.yaml vehicles/mytruck.yaml
```

Edit:

- `slug` — your entity prefix. Must match the `name:` in the Torque platform YAML (step 1).
- `torque:` — the entity IDs Torque created on *your* vehicle after the first upload (Settings → Entities, filter
  by the slug). Blank out anything you don't have; the generator omits those cards and alerts.
- `diesel` / `tire_alerts` — switch the DPF/regen/DEF and TPMS features.
- `items` — your maintenance schedule. Pull intervals from the owner's manual; the example is Ford's 2011–16 6.7L
  schedule on the severe-duty column. Keys ending in `_check` are inspection timers.
- `alerts` — thresholds for phone notifications.
- `notify` — your mobile app notify service.

## Generate and install

```
python3 gen.py vehicles/mytruck.yaml
cp out/mytruck.yaml /config/packages/
```

Restart HA (packages that add helpers need a full restart; later edits to templates/automations only need a
YAML reload).

Dashboard: Settings → Dashboards → **Add dashboard** → *New dashboard from scratch*, title and URL = your
`dashboard_url`. Open it → ⋮ → **Raw configuration editor** → paste `out/mytruck-dashboard.yaml` → Save.

## Using it

- **Overview**: odometer (auto-synced from the Torque odometer PID when present; otherwise type it), the Due
  list (anything ≥85 % of its interval), at-a-glance gauges, live Torque values.
- **Maintenance**: set each item's *last done at / on* once (your records, the dealer printout, or the Garage's
  Carfax import does it for you). To log work: pick the item, mileage (0 = current odometer), notes, tick anything
  "also done at the same time", Save. It stamps the timers, writes the Garage, and appends to Service History.
- **Diagnostics**: gauges, graphs, regen counter (diesel), tire targets. Set your tire-pressure targets here —
  alerts fire at target − 5 psi on the lowest tire, and when one tire is >6 psi below the others.
- **Parts**: in-stock and to-buy lists with +/− quantities and a barcode scanner button.
- **Garage**: opens the add-on; shows record counts.

### Engine hours

Torque's "run time since engine start" resets every start; an automation banks each run so `sensor.<slug>_engine_hours`
is a true hour meter from the day you install. Useful for vehicles whose manufacturer rates filters in hours.

### Regen detection (diesel)

Two detectors: exhaust temps (EGT 2–4 above 950 °F for 2 min) and a soot-load drop of >25 points. Either one counts
a regen, stamps date/odometer and notifies you. The second catches regens the first one misses.

## Re-generating

Edit the vehicle file, run `gen.py` again, copy the package over the old one, reload. Entity IDs are stable as long
as the item labels don't change (template sensors carry a `unique_id` derived from the key, so renaming a label keeps
history but you'll need to rename the entity in Settings → Entities to match the new dashboard).
