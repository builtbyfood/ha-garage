# 5 · Parts Intake add-on (optional) — photo → shopping list

Take a photo of a part box or a screenshot of a listing, upload it to a media folder, and it lands on your
"to buy" list with the part number — decoded locally with zbar (barcodes) and Tesseract (printed text). No cloud
AI, ~120 MB RAM, 1–3 s per image on a low-end x86 box.

## Install

1. Copy `addons/parts_intake/` to `/addons/parts_intake/`, Check for updates, Install, Start.
2. Configuration: `watch_dir` (default `/media/parts_intake`), `event_type`, `upc_lookup` (set `false` for fully
   offline — otherwise UPCs are looked up on upcitemdb's free tier to get a product name).
3. The package includes the automation that listens for the event and adds the item to the to-buy list.

## Use

- **Photo / screenshot**: HA app → Media → My media → `parts_intake` → Upload. A few seconds later the item is on
  the list and your phone gets a notification. Processed images move to `processed/` with a JSON sidecar.
- **Barcode in hand**: let the phone camera decode it, then Share → Home Assistant with the text `part: <number>`.
  (The companion app's share target only carries text, which is why photos go through the media folder.)

## Part-number patterns

Built in: Motorcraft (`FL-2051S`, `FD-4615`, `BXT-65-750`…) and Ford engineering numbers (`BC3Z-6A785-A`).
Add your make's pattern as a regex in the add-on's `extra_patterns` option, e.g. Toyota `^\d{5}-\d{5}$`.
