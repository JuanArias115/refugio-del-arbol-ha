#!/usr/bin/with-contenv bashio
set -eu

echo "Starting Refugio del Arbol guest portal on port 8099"
exec python3 /app.py
