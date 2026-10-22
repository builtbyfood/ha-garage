#!/usr/bin/with-contenv bashio
export WATCH_DIR="$(bashio::config 'watch_dir')"
export PROCESSED_SUBDIR="$(bashio::config 'processed_subdir')"
export WEBHOOK_ID="$(bashio::config 'event_type')"
export POLL_SECONDS="$(bashio::config 'poll_seconds')"
export OCR_LANG="$(bashio::config 'ocr_lang')"
export UPC_LOOKUP="$(bashio::config 'upc_lookup')"
export KEEP_ORIGINALS="$(bashio::config 'keep_originals')"
export EXTRA_PATTERNS="$(bashio::config 'extra_patterns' | tr '\n' '|')"
export LOG_LEVEL="$(bashio::config 'log_level')"
export HA_URL="http://supervisor/core"
bashio::log.info "Parts intake watching ${WATCH_DIR}"
exec python3 -u /intake.py
