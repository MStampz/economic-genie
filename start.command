#!/bin/bash
# Double-click in Finder to start Economic Genie. Docker Desktop must be installed.
cd "$(dirname "$0")" || exit 1

# Docker Desktop's command-line tools are not always on the PATH; use the copy inside the app.
command -v docker >/dev/null 2>&1 || export PATH="$PATH:/Applications/Docker.app/Contents/Resources/bin"

if ! docker info >/dev/null 2>&1; then
  echo "Starting Docker Desktop..."
  open -a Docker
  until docker info >/dev/null 2>&1; do sleep 2; done
fi

echo "Starting Economic Genie (the first start takes a few minutes)..."
docker compose up -d --build || { echo "Could not start. See the messages above."; read -r -p "Press Enter to close."; exit 1; }

PORT=$(grep -E '^GENIE_PORT=' .env 2>/dev/null | cut -d= -f2)
URL="http://localhost:${PORT:-3000}"
until curl -fs "$URL/api/health" >/dev/null 2>&1; do sleep 2; done
echo "Economic Genie is running at $URL"
open "$URL"
