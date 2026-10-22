# 2 · Custom PIDs: import, find, create

Standard OBD-II gives every car RPM, speed, coolant temperature, load, intake temp, fuel level (most), battery
voltage and a few dozen more. Torque shows those automatically. The useful stuff — **odometer, transmission
temperature, oil temperature, tire pressures, DPF soot, oil-life %** — is manufacturer-specific and has to be
added to Torque as a *custom PID*. Three routes, easiest first.

## A. Import a ready-made set

This repo ships verified CSVs under `pids/`. To import:

1. Copy the CSV to the phone at `/storage/emulated/0/.torque/extendedpids/` (the `.torque` folder is hidden;
   create `extendedpids` if missing). Any file manager, or `adb push file.csv /sdcard/.torque/extendedpids/`.
2. Torque → Settings → **Manage extra PIDs/Sensors** → ⋮ → **Add predefined set** → choose the file.
3. Settings → Data Logging & Upload → *Select what to log* → tick the new PIDs.
4. Drive. Each appears in HA as `sensor.<slug>_<pid name slugified>` (PID *Name* `Odometer` → `sensor.truck_odometer`).

A PID that stays at 0, reads garbage, or never appears means that module doesn't answer it — common across model
years even within one engine family. Delete it; don't tune blind.

## B. Install a Torque plugin for your platform

Some platforms have plugins on Google Play that pre-package PIDs (search Play for "Torque" + your make). They
appear in Torque automatically after install. Example: the "Ford Superduty" plugin adds TPMS and per-cylinder
fuel-balance rates for Super Duty trucks.

## C. Find and create your own

### Where the numbers come from

| Source | What you'll find |
|---|---|
| Model-specific forums (Ford Truck Enthusiasts, Diesel Stop, GM-Trucks, Cummins Forum, Toyota Nation, Tacoma World, Ram Forum, F150 Forum, Bimmerpost, etc.) — search *"Torque Pro PIDs"* or *"extended PIDs"* | member-tested CSVs and equations |
| [torque-bhp.com forum](https://torque-bhp.com/community/) | per-vehicle threads, often the originals |
| [Wikipedia: OBD-II PIDs](https://en.wikipedia.org/wiki/OBD-II_PIDs) | every *standard* Mode 01 PID with byte formulas, incl. the diesel block (turbo, VGT, EGR, DPF, NOx, DEF) |
| FORScan (Ford/Mazda), Tech2/GDS (GM), Techstream (Toyota), VCDS (VW) PID lists | the manufacturer's own DIDs and scaling — the gold standard when a forum equation disagrees |
| Other apps' profiles (Car Scanner, OBD Fusion, Scan My Tesla…) | sometimes publish their PID definitions; the DIDs transfer, the equation syntax doesn't |

Rules of thumb: a thread for *your exact year range and engine* beats a general one; headers (which module to
ask) change between generations; "works on my 2019" tells you nothing about a 2014.

### Anatomy of a custom PID

Torque → Settings → Manage extra PIDs/Sensors → **Add custom PID**:

| Field | Meaning | Example |
|---|---|---|
| OBD2 Mode and PID | mode + parameter, hex. `01xx` = standard, `22xxxx` = manufacturer DID (UDS ReadDataByIdentifier) | `22404C` |
| Long name / short name | Long name becomes the HA entity name | `Odometer` / `ODO` |
| Minimum / maximum value | gauge range only | `0` / `999999` |
| Scale factor | multiplier applied after the equation | `1` |
| Unit type | display unit | `mi` |
| **Equation** | how to turn the reply bytes `A B C D …` into a number | `((A<16)+(B<8)+C)*0.0621371` |
| **OBD Header** | CAN ID of the module to query. Blank = default (engine ECU) | `720` |
| Start/stop diagnostic command | rarely needed; leave blank | |

Equation syntax: `A`…`H` are reply bytes; `+ - * /`; `<` shifts left (`A<8` = A×256); `SIGNED(A)` for
two's-complement; `BIT(A,3)` for a flag; `INT16(A:B)` on newer Torque builds; `VALUE` for the raw value.
Temperature replies are usually `A-40` (°C); add `*(9/5)+32` for °F. Pressures are often kPa — `*0.145` for psi.
Distances are usually km — `*0.621371` for miles.

Common headers by make (verify on your vehicle):

| Make | Engine | Transmission | Cluster / body (odometer, TPMS) |
|---|---|---|---|
| Ford / Lincoln | `7E0` | `7E1` | `720` cluster, `726` BCM |
| GM | `7E0` | `7E2` (some) | `7E0` for many body items |
| Toyota / Lexus | `7E0` | `7E1` | `7C0` combination meter |
| Stellantis (Ram/Jeep) | `7E0` | `7E1` | `620`-range BCM on newer |
| VW group | `7E0` | `7E1` | module-specific; see VCDS lists |

### Test before you log

Add the PID, then on the custom-PID screen use **Test** (or watch it on a realtime gauge) with the engine
running. Checks:

- Does it respond at all? No reply → wrong header or unsupported DID.
- Does the number make sense? Odometer should match the dash; trans temp at idle is near coolant temp;
  tire pressures should match a gauge; soot should move with driving, not jump.
- Does it change when it should? Rev the engine for load/boost, drive for odometer.

Only then tick it in *Select what to log*. Torque's web upload is PIDs only; each logged PID costs recorder space
in HA, so keep the list to what you'll actually use.

### Submit it back

Export from Torque (Manage extra PIDs → ⋮ → *Export*) or write the CSV by hand in this format:

```
Name,ShortName,ModeAndPID,Equation,Min Value,Max Value,Units,Header
Transmission Fluid Temp,TFT,221E1C,((SIGNED(A)*256)+B)*(9/80)+32,0,300,F,7E1
```

Save it as `pids/<make>_<engine>_<years>.csv`, note which PIDs you verified and on what model year in a comment
at the top of your PR, and others get your work for free.

## Included files

| File | Verified on | Notes |
|---|---|---|
| `ford_67L_powerstroke_2011-2016.csv` | 2016 F-350 | odometer (cluster), TFT, EOT, DPF soot, TPMS, DEF, FRP, plus Mode 01 diesel fallbacks (most unsupported on 2016; NOx and EGR temp work). No oil-pressure PID — these years have a switch, not a sensor |

Your make not here yet? That's the PR we most want.
