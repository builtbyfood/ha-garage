# Notes for forks

- `garage/server.py`: helper entity IDs are built from `HELPER_PREFIX` (run.sh sets it from the `vehicle_slug`
  option). Categories and the keys synced to HA live in `CATEGORIES` / `HA_KEYS`; add yours there and in your
  vehicle file.
- `parts_intake/intake.py`: part-number regexes default to Motorcraft/Ford formats; extend via the
  `extra_patterns` option rather than editing the file.
- Both add-ons talk to HA through the Supervisor proxy (`http://supervisor/core`) with the token the Supervisor
  injects; nothing to configure.
