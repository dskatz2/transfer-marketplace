# H-2A Transfer Matcher

Internal tool for surfacing H-2A worker transfer opportunities: a worker can move
from a contract ending on date E to one starting on date S if `0 <= (S - E).days <= 30`.
Only contracts with 25+ workers are considered.

## Run it

```bash
cd h2a-transfer-matcher
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8811
```

Then open http://localhost:8811.

## Using it

1. **Admin tab** — upload the quarterly DOL disclosure `.xlsx` and the
   `active_customers_enterprises.csv`. Re-uploading either one re-runs matching
   across everything (disclosure rows are upserted by `CASE_NUMBER`; the customer
   list is fully refreshed).
2. Review queue — employer names that fuzzy-matched a Seso customer with medium
   confidence (78–92%) land here for a human call. Above 92% auto-confirms;
   below 78% is treated as a prospect.
3. **Dashboard tab** — a "best matches right now" panel (KPIs + charts), plus
   Seso Customer ↔ Seso Customer and Seso Customer ↔ Prospect match tables,
   sortable by workers/gap/soonest. Each row has a **Dismiss** button; dismissed
   matches can be restored individually or all at once from Admin.
4. **Search tab** — type a contract date and worker count directly (works for a
   brand-new prospect that isn't in the disclosure data at all), or look up an
   existing filing first to prefill those fields. Choose "Needs workers" or
   "Save on outbound transportation" to see which Seso customers line up.

## Notes on the logic

- Worker count = `TOTAL_WORKERS_H2A_CERTIFIED`, falling back to
  `TOTAL_WORKERS_H2A_REQUESTED` when certified is 0.
- Only `Certification` / `Partial Certification` statuses (including Expired)
  count as real contracts; Withdrawn/Denied are excluded.
- A contract whose real end date has already passed is projected forward by
  exactly one year for matching purposes (H-2A jobs are seasonal and repeat
  annually), so the dashboard still surfaces a same-season opportunity for the
  next cycle. These are flagged "Projected" in the UI; everything else is a
  confirmed contract on file.
- Multi-entity customers (see the CSV's Enterprise Account Name grouping) are
  treated as one customer regardless of which legal entity/FEIN filed.

## Data note

The disclosure file contains FEINs, personal contact emails/phones, and other
sensitive fields. Set `APP_USERNAME`/`APP_PASSWORD` (see below) before putting
this anywhere reachable off your own machine — without them the app has no
login at all.

## Deploying to Vercel

The app is structured for Vercel: `api/index.py` is the serverless entrypoint
(FastAPI, routed at `/api/*` via `vercel.json`), everything under `public/` is
served directly by the platform, and `app/database.py` switches from local
SQLite to Postgres automatically when a `POSTGRES_URL` or `DATABASE_URL`
env var is present.

1. Push this repo to GitHub.
2. On [vercel.com](https://vercel.com), import the repo as a new project.
3. In the project's **Storage** tab, add a Postgres database (Vercel
   Postgres/Neon) — this sets `POSTGRES_URL` automatically.
4. In **Settings → Environment Variables**, add `APP_USERNAME` and
   `APP_PASSWORD` (the login for the whole app).
5. Deploy. Tables are created automatically on first request.
6. Open the live URL, log in, and use the Admin tab to upload the disclosure
   `.xlsx` and customer `.csv` — same as local.

Ingestion uses bulk insert/update (not one query per row) specifically so a
17k-row upload stays well within a serverless function's execution time limit
against a networked Postgres database.
