# Add-ons

`garage/` and `parts_intake/` are complete local add-ons: copy a folder to `/addons/` on the HA host, then
Add-on Store → ⋮ → Check for updates → Local add-ons → Install. Both take the vehicle slug as an option; run one
Garage instance per vehicle (copy the folder, change `slug:` and `name:` in `config.yaml`).

See `docs/04-garage-addon.md` and `docs/05-parts-intake-addon.md`.
