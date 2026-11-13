# Running Economic Genie on your Mac

## What runs

Docker Desktop runs three small containers, started together by `docker compose`:

| Container | What it does |
|-----------|--------------|
| `db`  | Postgres database. Your data is stored in the Docker volume `economic-genie_genie-data`. |
| `api` | The Python API. On every start it first updates the database schema if needed. |
| `web` | The web app, served on http://localhost:3000. It forwards `/api` to the API. |

Only `web` is reachable from outside Docker, and by default only from this Mac.

## Start, stop, update

- Start: double-click `start.command` (or `docker compose up -d --build`).
- Stop: double-click `stop.command` (or `docker compose stop`). Data is kept.
- Update to a newer version: download the new code, then start again. The schema is migrated automatically.
- See what is happening: `docker compose logs -f api`.

## Use it from your phone at home

1. Copy `.env.example` to `.env` and set `GENIE_BIND=0.0.0.0`.
2. Start again. On your phone (same Wi-Fi), open `http://<your-mac-name>.local:3000`.
   Find the name in System Settings → General → Sharing → Local hostname.

This uses plain http on your home network. Only do it on a network you trust. Hosting with https comes later.

## Backups

Run `./scripts/backup.sh` in Terminal. It writes `backups/genie-<date>.sql.gz` (readable only by you).
Copy these somewhere safe, for example an encrypted external disk.

Restore a backup into a running app:

```bash
gunzip -c backups/genie-<date>.sql.gz | docker compose exec -T db psql -U genie -d genie
```

## Start over with an empty database

This deletes all data. Make a backup first.

```bash
docker compose down -v
```

## Path to cloud hosting

The same containers run on a cloud host. The database moves to a managed Postgres (with automatic backups), the
web app gets a domain and https, and `GENIE_COOKIE_SECURE=true` is set. No code changes are needed for that step.
