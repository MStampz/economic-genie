# Economic Genie

A personal finance tool for pulling in my National Australia Bank (NAB) transaction data, categorising spending, and building a spending overview plus scenario planning.

## Goals

1. **Import transactions.** Get all NAB account data into one local store.
2. **Categorise spending.** Rule-based categories (groceries, transport, bills, etc.) with manual overrides.
3. **Spending overview.** A dashboard showing monthly spend by category, trends, recurring payments and cash flow.
4. **Scenario planning.** "What if" modelling: cutting a category, a pay rise, a new loan or mortgage, savings targets over time.

## Data sources (phased)

### Phase 1: NAB CSV exports
- Export transactions from NAB Internet Banking as CSV, per account.
- Drop files into `data/raw/` (git-ignored, never committed).
- An importer normalises them (date, amount, description, account, balance) and de-duplicates overlapping exports.

### Phase 2: Open banking via CDR
- Australia's Consumer Data Right (CDR) gives read-only access to bank data, but only through an accredited data recipient.
- Plan to use an intermediary such as [Basiq](https://basiq.io) or [Fiskil](https://fiskil.com) to connect NAB and sync transactions automatically.
- The importer interface stays the same, so CSV and CDR sources feed the same store.

## Rough architecture

```
data/raw/            NAB CSV exports (git-ignored)
importers/           CSV importer now, CDR (Basiq/Fiskil) importer later
store/               local database (e.g. SQLite) of normalised transactions
categorise/          rules + overrides
dashboard/           spending overview UI
scenarios/           scenario planning models
```

## Privacy

This repo holds code only. Bank exports, databases and API credentials stay local and are listed in `.gitignore`.

## Status

Just started: README and plan only.
