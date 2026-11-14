# Economic Genie

A family finance app: import your bank transactions, categorise spending, and (soon) track it against a budget.
It runs on your own Mac with Docker Desktop and is built so it can move to cloud hosting later.

**Status:** increment 1 (the core: logins, family groups with invite codes, CSV import from any bank, internal
transfer detection, category rules) and increment 2 (the spending overview and budgets, as prototyped) are built.
Next is increment 3 (the AI coach).

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

Export a CSV file from your bank's internet banking and drop it on the **Import** tab.

- **Known formats** (NAB today) are recognised from the file's columns and imported straight away.
- **Any other bank's CSV:** the first time, you match its columns (date, amount or money out/in, description,
  account) with a live preview. The layout is saved for your group, so the next file from that bank imports
  straight away. Files with or without a header row, with `,` `;` or tab separators, and amounts like `(12.00)`,
  `12.00 DR` or `$1,234.56` all work.
- Import as often as you like: overlapping files are fine, rows you already have are skipped, and pending card
  authorisations are replaced when they settle. Card payments from your transaction account are matched to the card
  and not counted as spending.

Every source becomes the same common row (`ParsedRow`) before it is stored, so open banking (Basiq, Fiskil) will be
one more connector in `backend/app/ingestion/connectors/` feeding the same pipeline.

## Overview and budget

The **Overview** tab shows a month (or all data, or one account): total spent, the running total with daily spending
split by budget post, insights (eating out per week, most frequent merchant, biggest day, fees), where the money went,
each budget post against its monthly amount (with a pace marker in the current month), a spending calendar, spending
per account, top merchants and recurring charges. Tap a post or a day to see its transactions.

The **Budget** tab sets up headings (e.g. "Faste udgifter") and posts (e.g. "Groceries og wine"). Each post covers one
or more categories and can have a monthly amount; a category belongs to one post only. A new group can start from the
prototype's budget. All figures are computed by the API (`app/modules/budgets/overview.py`), not in the browser.

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
