# Economic Genie

A family finance app: import your bank transactions, categorise spending, and (soon) track it against a budget.
It runs on your own Mac with Docker Desktop and is built so it can move to cloud hosting later.

**Status:** increment 1 (the core) is built: logins, family groups with invite codes, NAB CSV import, internal
transfer detection and category rules. Next is increment 2 (spending overview and budgets, as prototyped), then
increment 3 (the AI coach).

## Run it on your Mac

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running.

1. Download this repository (Code → Download ZIP, or `git clone`).
2. Double-click **`start.command`**. The first start builds the app and takes a few minutes.
   (If macOS blocks it, right-click → Open, or run `./start.command` in Terminal.)
3. Your browser opens **http://localhost:3000**. Create your account, then create your family group.
4. In the **Family** tab, tap **Invite someone** and give the code to your partner. They create their own account
   and choose **Join with an invite code**.

To stop: double-click `stop.command`. Your data is kept in a Docker volume and survives restarts and updates.

More detail, including using it from your phone at home and backups: [docs/run-on-mac.md](docs/run-on-mac.md).

## Import transactions

In NAB Internet Banking, open an account, choose **Export**, pick **CSV** and a date range, then drop the file on
the **Import** tab. Import as often as you like: overlapping files are fine, rows you already have are skipped, and
pending card authorisations are replaced when they settle. Credit card payments from your transaction account are
matched to the card and not counted as spending.

To load the rules from the prototype, open **Rules → Import rules (JSON)** and pick
[`examples/prototype-rules.json`](examples/prototype-rules.json), then tap **Apply rules**.

## How it is built

```
backend/   Python API (FastAPI, SQLAlchemy, Alembic, Postgres)
  app/core/        users, login, groups, invites, accounts, categories, rules, transactions, activity log
  app/ingestion/   connectors turn a bank format into rows; the pipeline dedupes, categorises and pairs transfers
  app/modules/     feature modules on top of the core (budgets next, the coach later)
  migrations/      database schema versions
  tests/           API tests (synthetic data only)
frontend/  React + TypeScript web app, phone-first, served by nginx which also forwards /api
docker-compose.yml   database + API + web app
```

- **Data belongs to a group** (a family). Every API route checks membership; non-members get "not found".
- **Category precedence:** a category you pick by hand always wins, then your rules, then NAB's own category.
- **New banks or open banking (Basiq/Fiskil)** means adding a connector in `app/ingestion/connectors/`.
- **Prepared for the coach, hidden for now:** transactions carry a value tag (valued / necessity / drift) with its
  source, and there are tables for goals and value profiles (with the chosen coach persona). AI use needs a per-user
  consent that is off by default. All figures are computed by the API, never by the AI.

## Security

- Passwords are hashed with Argon2. Sessions are random tokens in an HttpOnly, SameSite cookie; only a hash of the
  token is stored. Repeated failed logins are throttled.
- Every request that changes data needs a custom header, which blocks cross-site form attacks.
- Invite codes are single-use, expire after 7 days and are stored hashed.
- Group actions are recorded in an activity log, without secrets.
- The app listens on this Mac only unless you choose otherwise. Bank files and databases are never committed.

## Development

```bash
cd backend && pip install -e ".[dev]" && pytest          # tests use SQLite by default
GENIE_TEST_DATABASE_URL=postgresql+psycopg://... pytest  # or a throwaway Postgres database
uvicorn app.main:app --reload                            # API on :8000 (needs GENIE_DATABASE_URL)
cd frontend && npm install && npm run dev                # web app on :5173, forwards /api to :8000
```

Schema changes: edit `app/core/models.py`, then `alembic revision --autogenerate -m "..."` and commit the migration.
