# 0 · Overview — how the pieces fit

```
  OBD-II port ──► dongle ──► Torque Pro (phone) ──HTTPS──► Home Assistant
   (any car)   BT / Wi-Fi     logs the PIDs you          /api/torque  → sensor.<slug>_*
                              choose, uploads every             │
                              10–30 s while driving             ▼
                                                     package (generated per vehicle)
                                                     ├─ maintenance timers  (miles + months)
                                                     ├─ odometer sync, engine hours
                                                     ├─ alerts → your phone
                                                     └─ regen counter (diesel), tire targets
                                                                │
                              ┌─────────────────────────────────┼──────────────────────────┐
                              ▼                                 ▼                          ▼
                     Vehicle dashboard                   Garage add-on                 Parts Intake add-on
                     Overview · Diagnostics ·            service log · components ·   photo → barcode/OCR →
                     Maintenance · Parts · Garage        mods · inspections ·          "to buy" list
                                                         Carfax import · CSV export
```

**Works for any vehicle Torque can read.** Standard OBD-II (1996+ US, 2001+ EU petrol, 2004+ EU diesel) gives
every car the basics; manufacturer PIDs add odometer, transmission temperature, tire pressure and the like, and
differ per make — see the PID docs. Diesel-only features (DPF soot, regen counting, DEF) and TPMS switch on or off
per vehicle in one YAML file. Multiple vehicles coexist with different slugs.

**What's phone-dependent:** live data and odometer sync only arrive while Torque is running and connected.
Maintenance timers, the Garage, parts lists and alerts on stored data work regardless.

## Reading order

1. [Torque + dongle + HTTPS](01-torque-setup.md)
2. [Custom PIDs: import, find, create](02-pid-import.md)
3. [Home Assistant package + dashboard](03-home-assistant.md) and the [vehicle-file walkthrough](07-vehicle-file-walkthrough.md)
4. [Garage add-on](04-garage-addon.md)
5. [Parts Intake add-on](05-parts-intake-addon.md) (optional)
6. [Troubleshooting](06-troubleshooting.md)
