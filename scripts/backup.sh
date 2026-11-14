#!/bin/bash
# Saves a full copy of the database to backups/genie-YYYY-MM-DD-HHMM.sql.gz
# Restore: gunzip -c backups/<file>.sql.gz | docker compose exec -T db psql -U genie -d genie
set -euo pipefail
cd "$(dirname "$0")/.."

# Docker Desktop's command-line tools are not always on the PATH; use the copy inside the app.
command -v docker >/dev/null 2>&1 || export PATH="$PATH:/Applications/Docker.app/Contents/Resources/bin"
mkdir -p backups
file="backups/genie-$(date +%Y-%m-%d-%H%M).sql.gz"
docker compose exec -T db pg_dump -U genie -d genie --clean --if-exists | gzip > "$file"
chmod 600 "$file"
echo "Saved $file"
