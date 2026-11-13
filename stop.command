#!/bin/bash
# Double-click to stop Economic Genie. Your data is kept.
cd "$(dirname "$0")" || exit 1
docker compose stop
echo "Stopped. Your data is kept."
