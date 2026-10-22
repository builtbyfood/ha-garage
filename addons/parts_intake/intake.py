#!/usr/bin/env python3
"""F-350 Parts Intake — folder watcher that decodes barcodes and OCRs part numbers.

Pipeline per image:
  1. wait until the file stops growing (upload finished)
  2. zbarimg  -> barcodes (UPC/EAN/Code128/QR)
  3. tesseract -> text (two passes: raw + preprocessed)
  4. regex     -> Ford / Motorcraft part numbers
  5. optional UPC lookup (upcitemdb trial API, no key)
  6. POST JSON to Home Assistant webhook
  7. move image (+ .json sidecar) to <watch_dir>/<processed_subdir>/

Runs standalone too:  python3 intake.py --once /path/to/image.jpg
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from PIL import Image, ImageOps

# ---------------------------------------------------------------- config
WATCH_DIR = Path(os.environ.get("WATCH_DIR", "/media/f350_parts"))
PROCESSED_SUBDIR = os.environ.get("PROCESSED_SUBDIR", "processed")
WEBHOOK_ID = os.environ.get("WEBHOOK_ID", "f350_parts_intake")
POLL_SECONDS = float(os.environ.get("POLL_SECONDS", "2"))
OCR_LANG = os.environ.get("OCR_LANG", "eng")
UPC_LOOKUP = os.environ.get("UPC_LOOKUP", "true").lower() == "true"
KEEP_ORIGINALS = os.environ.get("KEEP_ORIGINALS", "true").lower() == "true"
EXTRA_PATTERNS = [p for p in os.environ.get("EXTRA_PATTERNS", "").split("|") if p.strip()]
HA_URL = os.environ.get("HA_URL", "http://supervisor/core").rstrip("/")
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "info").upper()

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}

logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("intake")

# ---------------------------------------------------------------- part-number patterns
# Motorcraft: FL-2051S, FD-4615, FA-1927, FP-79, BXT-65-750, XO-15W40-5QSD, XT-10-QLVC, VC-13-G
MOTORCRAFT = re.compile(
    r"\b(?:FL|FD|FA|FP|FG|FT|BXT|BXL|XO|XT|XY|XL|VC|WP|SP|DG|AGSF|PM|KC|BRF|BRRF|BRSP|MKD|HD)"
    r"-?\d{1,5}[A-Z]{0,4}(?:-[A-Z0-9]{1,6}){0,2}\b",
    re.I,
)
# Ford engineering / service numbers: BC3Z-6A785-A, HC3Z-9N184-B, AL3Z-1005-A
FORD_ENG = re.compile(r"\b[A-Z0-9]{2}\d[A-Z]-\d[A-Z0-9]{3,5}-[A-Z]{1,2}\b", re.I)
EXTRA = [re.compile(p, re.I) for p in EXTRA_PATTERNS]

UPC_TYPES = {"EAN-13", "UPC-A", "UPC-E", "EAN-8", "ISBN-13"}


def run(cmd: list[str], timeout: int = 60) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode not in (0, 4) and r.stderr.strip():  # zbarimg exits 4 when no symbols found
            log.warning("%s rc=%s: %s", cmd[0], r.returncode, r.stderr.strip()[:300])
        elif r.stderr.strip():
            log.debug("%s stderr: %s", cmd[0], r.stderr.strip()[:300])
        return r.stdout
    except Exception as e:  # noqa: BLE001
        log.warning("command failed %s: %s", cmd[0], e)
        return ""


# ---------------------------------------------------------------- decoders
# ---- libzbar via ctypes: feeds raw Y800 pixels from Pillow, so no ImageMagick delegates are needed
import ctypes, ctypes.util  # noqa: E402

_ZBAR = None


def _load_zbar():
    global _ZBAR
    if _ZBAR is not None:
        return _ZBAR or None
    for name in ("libzbar.so.0", "libzbar.so", ctypes.util.find_library("zbar")):
        if not name:
            continue
        try:
            lib = ctypes.CDLL(name)
            break
        except OSError:
            continue
    else:
        log.error("libzbar not found; barcode decoding disabled")
        _ZBAR = False
        return None
    P = ctypes.c_void_p
    lib.zbar_image_scanner_create.restype = P
    lib.zbar_image_scanner_set_config.argtypes = [P, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    lib.zbar_image_create.restype = P
    lib.zbar_image_set_format.argtypes = [P, ctypes.c_ulong]
    lib.zbar_image_set_size.argtypes = [P, ctypes.c_uint, ctypes.c_uint]
    lib.zbar_image_set_data.argtypes = [P, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]
    lib.zbar_scan_image.argtypes = [P, P]
    lib.zbar_scan_image.restype = ctypes.c_int
    lib.zbar_image_first_symbol.argtypes = [P]
    lib.zbar_image_first_symbol.restype = P
    lib.zbar_symbol_next.argtypes = [P]
    lib.zbar_symbol_next.restype = P
    lib.zbar_symbol_get_type.argtypes = [P]
    lib.zbar_symbol_get_type.restype = ctypes.c_int
    lib.zbar_symbol_get_data.argtypes = [P]
    lib.zbar_symbol_get_data.restype = ctypes.c_char_p
    lib.zbar_get_symbol_name.argtypes = [ctypes.c_int]
    lib.zbar_get_symbol_name.restype = ctypes.c_char_p
    lib.zbar_image_destroy.argtypes = [P]
    lib.zbar_image_scanner_destroy.argtypes = [P]
    _ZBAR = lib
    return lib


def _zbar_scan(img: "Image.Image") -> list[dict]:
    lib = _load_zbar()
    if not lib:
        return []
    gray = img.convert("L")
    w, h = gray.size
    raw = gray.tobytes()
    buf = ctypes.create_string_buffer(raw, len(raw))
    scanner = lib.zbar_image_scanner_create()
    lib.zbar_image_scanner_set_config(scanner, 0, 0, 1)  # ZBAR_NONE, ZBAR_CFG_ENABLE, on
    zimg = lib.zbar_image_create()
    lib.zbar_image_set_format(zimg, int.from_bytes(b"Y800", "little"))
    lib.zbar_image_set_size(zimg, w, h)
    lib.zbar_image_set_data(zimg, buf, len(raw), None)
    found = []
    try:
        if lib.zbar_scan_image(scanner, zimg) > 0:
            sym = lib.zbar_image_first_symbol(zimg)
            while sym:
                typ = lib.zbar_get_symbol_name(lib.zbar_symbol_get_type(sym)).decode()
                data = (lib.zbar_symbol_get_data(sym) or b"").decode(errors="replace")
                if data:
                    found.append({"type": typ, "data": data})
                sym = lib.zbar_symbol_next(sym)
    finally:
        lib.zbar_image_destroy(zimg)
        lib.zbar_image_scanner_destroy(scanner)
    return found


def decode_barcodes(path: Path) -> list[dict]:
    """Try as-is, then autocontrast, then 2x upscale (small phone shots)."""
    try:
        base = ImageOps.exif_transpose(Image.open(path)).convert("L")
    except Exception as e:  # noqa: BLE001
        log.warning("cannot open %s: %s", path.name, e)
        return []
    variants = [base, ImageOps.autocontrast(base)]
    variants.append(variants[1].resize((base.width * 2, base.height * 2), Image.LANCZOS))
    for v in variants:
        found = _zbar_scan(v)
        if found:
            return found
    return []


def preprocess(path: Path, scale: float = 2.0, fmt: str = "png") -> Path | None:
    try:
        img = Image.open(path)
        img = ImageOps.exif_transpose(img).convert("L")
        img = ImageOps.autocontrast(img)
        if scale != 1.0:
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
        tmp = path.with_suffix(f".pre.{fmt}")
        img.save(tmp)
        return tmp
    except Exception as e:  # noqa: BLE001
        log.warning("preprocess failed: %s", e)
        return None


def ocr(path: Path) -> str:
    """Two tesseract passes (raw, preprocessed) with two layout modes, merged."""
    texts = []
    for psm in ("6", "11"):
        texts.append(run(["tesseract", str(path), "-", "-l", OCR_LANG, "--psm", psm]))
    tmp = preprocess(path)
    if tmp:
        for psm in ("6", "11"):
            texts.append(run(["tesseract", str(tmp), "-", "-l", OCR_LANG, "--psm", psm]))
        tmp.unlink(missing_ok=True)
    return "\n".join(texts)


def extract_part_numbers(text: str) -> list[str]:
    found: dict[str, int] = {}  # part number -> first position in text
    for rx in [MOTORCRAFT, FORD_ENG, *EXTRA]:
        for m in rx.finditer(text):
            pn = m.group(0).upper().replace(" ", "")
            # normalize "FL2051S" -> "FL-2051S" for Motorcraft prefixes
            pn = re.sub(r"^([A-Z]{2,4})(\d)", r"\1-\2", pn) if rx is MOTORCRAFT and "-" not in pn[:5] else pn
            found[pn] = min(found.get(pn, m.start()), m.start())
    # order by where they first appear on the page (labels like "Part Number:" come first)
    return sorted(found, key=found.get)


def upc_lookup(code: str) -> dict:
    """Free upcitemdb trial endpoint (rate-limited, ~100/day, no key)."""
    if not UPC_LOOKUP:
        return {}
    try:
        r = requests.get(
            "https://api.upcitemdb.com/prod/trial/lookup",
            params={"upc": code},
            timeout=10,
            headers={"User-Agent": "f350-parts-intake/0.1"},
        )
        if r.ok:
            items = r.json().get("items") or []
            if items:
                it = items[0]
                return {"title": it.get("title"), "brand": it.get("brand"), "model": it.get("model")}
    except Exception as e:  # noqa: BLE001
        log.info("upc lookup skipped: %s", e)
    return {}


# ---------------------------------------------------------------- HA
def post_webhook(payload: dict) -> bool:
    """Fire HA event <EVENT_TYPE> (default f350_parts_intake) via the Supervisor core proxy."""
    url = f"{HA_URL}/api/events/{WEBHOOK_ID}"
    headers = {"Content-Type": "application/json"}
    if SUPERVISOR_TOKEN:
        headers["Authorization"] = f"Bearer {SUPERVISOR_TOKEN}"
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        log.info("event %s -> %s %s", WEBHOOK_ID, r.status_code, r.text.strip()[:80])
        return r.ok
    except Exception as e:  # noqa: BLE001
        log.error("webhook post failed: %s", e)
        return False


# ---------------------------------------------------------------- per-file
def best_name(barcodes, part_numbers, upc_info, text) -> str:
    if upc_info.get("title"):
        return upc_info["title"][:120]
    if part_numbers:
        return part_numbers[0]
    for bc in barcodes:
        if bc["type"] not in UPC_TYPES:
            return f"{bc['type']} {bc['data']}"[:120]
    for line in text.splitlines():
        line = line.strip()
        if len(line) >= 4:
            return line[:120]
    return "Unreadable part photo"


def process(path: Path, post: bool = True) -> dict:
    log.info("processing %s", path.name)
    barcodes = decode_barcodes(path)
    text = ocr(path)
    part_numbers = extract_part_numbers(text)
    upcs = [b["data"] for b in barcodes if b["type"] in UPC_TYPES]
    upc_info = upc_lookup(upcs[0]) if upcs else {}

    payload = {
        "file": path.name,
        "when": datetime.now().isoformat(timespec="seconds"),
        "name": best_name(barcodes, part_numbers, upc_info, text),
        "part_numbers": part_numbers,
        "barcodes": barcodes,
        "upc": upcs[0] if upcs else None,
        "upc_info": upc_info,
        "ocr_excerpt": " ".join(text.split())[:300],
        "confidence": "high" if (part_numbers or upc_info) else ("medium" if barcodes else "low"),
    }
    log.info("result: %s", json.dumps({k: payload[k] for k in ("name", "part_numbers", "upc", "confidence")}))

    if post:
        post_webhook(payload)

    # archive
    dest_dir = path.parent / PROCESSED_SUBDIR
    dest_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"{stamp}-{path.name}"
    (dest.with_suffix(dest.suffix + ".json")).write_text(json.dumps(payload, indent=2))
    if KEEP_ORIGINALS:
        shutil.move(str(path), str(dest))
    else:
        path.unlink(missing_ok=True)
    return payload


def file_is_stable(path: Path, wait: float = 1.0) -> bool:
    try:
        s1 = path.stat().st_size
        time.sleep(wait)
        return path.stat().st_size == s1 and s1 > 0
    except FileNotFoundError:
        return False


def watch() -> None:
    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    (WATCH_DIR / PROCESSED_SUBDIR).mkdir(exist_ok=True)
    log.info("libzbar: %s | tesseract: %s",
             "ok" if _load_zbar() else "MISSING",
             (run(["tesseract", "--version"]).splitlines() or ["missing"])[0].strip())
    log.info("watching %s every %ss (event=%s)", WATCH_DIR, POLL_SECONDS, WEBHOOK_ID)
    while True:
        try:
            for p in sorted(WATCH_DIR.iterdir()):
                if p.is_file() and p.suffix.lower() in IMAGE_EXT and ".pre." not in p.name:
                    if file_is_stable(p):
                        try:
                            process(p)
                        except Exception as e:  # noqa: BLE001
                            log.exception("failed on %s: %s", p.name, e)
                            (WATCH_DIR / PROCESSED_SUBDIR).mkdir(exist_ok=True)
                            shutil.move(str(p), str(WATCH_DIR / PROCESSED_SUBDIR / f"FAILED-{p.name}"))
        except Exception as e:  # noqa: BLE001
            log.exception("watch loop error: %s", e)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--once":
        print(json.dumps(process(Path(sys.argv[2]), post="--post" in sys.argv), indent=2))
    else:
        watch()
