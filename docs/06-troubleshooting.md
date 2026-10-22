# 6 · Troubleshooting

**Nothing arrives in HA**
- Browser → `https://ha.example.com/api/torque`: 401 = endpoint live; 404 = `platform: torque` not loaded (YAML indent, or no restart).
- HA log search `torque`: 401 entries = bad token (trailing space is the classic); nothing at all = the phone isn't sending.
- Torque: *Upload to web-server* ticked? *Select what to log* non-empty? GPS set to the phone (not "external") and location permission granted? Battery optimisation off?
- Phone on cellular can reach the URL? Open it in the phone browser; a 401 there proves connectivity.

**Entities appear, then vanish after an HA restart**
Normal. Torque sensors are created on upload and live only in memory; they come back on the next upload. The
dashboard shows "entity not found" until then. Everything the package itself creates persists.

**Entity names don't match the vehicle file**
Torque names sensors after the PID label, including its own "virtual" ECU duplicates (`ecu_7e9_*`). Untick the
duplicates in Torque, note the surviving entity IDs, update the vehicle file, regenerate.

**A custom PID reads 0 / garbage / never appears**
The module doesn't answer it on your year, or the header is wrong. Try the other common header for that module,
then delete it. See doc 02.

**Odometer doesn't auto-sync**
The sync automation accepts a reading only if it's above the helper and less than 5,000 mi above it (garbage
guard). Set the helper manually once to the real mileage.

**TPMS corners are mislabelled**
Sensor IDs follow the wheel; after a rotation the body module reports the old corner until a TPMS relearn. Alerts
use lowest-tire and spread, so they stay correct regardless.

**Regen never counts (diesel)**
EGT-based detection needs the post-turbo sensors; the soot-drop detector needs the soot PID. If neither PID is
supported on your engine, set `diesel: true` but leave those entries blank — the section still renders, the
counter just stays manual.

**Garage sensor is unknown**
The add-on isn't running or hasn't been updated. Add-on Store → ⋮ → *Check for updates* after any edit to the
add-on folder; Supervisor doesn't rescan `/addons` on its own.

**Add-on forms return 404 under ingress**
Fixed in the shipped `server.py` (absolute URLs from the `X-Ingress-Path` header). If you forked an older copy,
that's the fix.

**Too much recorder data**
Untick Torque's phone sensors (accelerometer, barometer, GPS-vs-OBD speed), set the web-logging interval to
20–30 s, and consider `recorder: exclude:` for the chatty PIDs you only want live.
