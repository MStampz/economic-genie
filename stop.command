#!/bin/bash
# Double-click to stop Economic Genie. Your data is kept.
cd "$(dirname "$0")" || exit 1

# Docker Desktop's command-line tools are not always on the PATH; use the copy inside the app.
command -v docker >/dev/null 2>&1 || export PATH="$PATH:/Applications/Docker.app/Contents/Resources/bin"
docker compose stop
echo "Stopped. Your data is kept."
