#!/usr/bin/with-contenv bashio
export SLUG="$(bashio::config 'vehicle_slug')"
export VEHICLE="$(bashio::config 'vehicle_name')"
export DB_PATH="$(bashio::config 'db_path')"
export ODOMETER_ENTITY="input_number.${SLUG}_odometer"
export HISTORY_TODO="todo.${SLUG}_service_history"
export HELPER_PREFIX="${SLUG}"
export LOG_LEVEL="$(bashio::config 'log_level')"
export HA_URL="http://supervisor/core"
export PORT=8099
bashio::log.info "Garage (${SLUG}) on :8099, db ${DB_PATH}"
exec python3 -u /server.py
