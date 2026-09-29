# Health Hub — web

A small Flask app so other people can create their own account (plain email +
password — no invite needed) and see a report built from their own data, in
the same visual style as the personal report. They import their own CGM
export, Quest blood work PDF, and DEXA scan PDF — using the exact same
parsers as your local Health Hub app (`importers/`), just wired up per-account
instead of into one local SQLite file. Blood work and body basics can also be
typed in by hand on the dashboard for anyone who doesn't have a file to
upload.

Whoop, Oura, and Apple Health exports can be uploaded from the dashboard too,
but there's no automatic parser wired up for any of them yet — the file is
saved, but nothing from it appears in the report until a real sample export
from each service has been used to build and test that parser. That's
intentional: guessing at a health-data file format without a real sample to
check against risks silently misreading someone's numbers.

**This is a separate project.** It does not touch, read, or write to your
personal local Health Hub app or its data — the `importers/*.py` files were
copied from it (read-only, unmodified) since they're generic parsers that
don't depend on your local single-user database. Everything else here is
new, meant to be deployed somewhere public so other people can use it.

## What you need before deploying

1. **Somewhere to host it.** Render is the simplest starting point for a
   small Flask app — free to start, though the free database expires after
   30 days, so budget for their small paid Postgres once you're ready to
   actually keep this running for people.
2. **A GitHub account** (or similar) — Render deploys from a git repo.

## Local test run (optional, before deploying)

```bash
cd healthhub-web
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: generate a real FLASK_SECRET_KEY (the file tells you how)
python3 app.py
# visit http://localhost:5000
```

There's also an automated smoke test: `python3 smoke_test.py`.

## Deploying to Render

1. Push this `healthhub-web` folder to a new GitHub repo (or use GitHub's
   "Add file → Upload files" button in the browser — no command line needed).
2. In Render: **New → Web Service**, connect that repo.
   - Runtime: Python 3
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app` (already in the `Procfile`, Render should pick it up automatically)
3. In Render: **New → PostgreSQL** (start on the free tier to test; move to
   paid before you actually invite people, since the free database expires
   after 30 days and would silently delete everyone's saved data).
4. On the web service's **Environment** tab, set:
   - `FLASK_SECRET_KEY` — a random 64-character string (Render can generate one for you, or use the command in `.env.example`)
   - `DATABASE_URL` — Render fills this in automatically once you attach the Postgres database to this web service (its "Internal Database URL")
5. Deploy. Visit your Render URL, click "Create one" to sign up with an email and password, and confirm the dashboard and report page work before sharing the link with anyone else.

## What's actually stored, and where

- Passwords are hashed, never stored in plain text.
- Blood work, body basics, CGM, labs, and DEXA data people enter or import:
  stored as normal account data in the Postgres database — not shared
  between users, not sent anywhere else.
- Whoop/Oura/Apple Health export files: saved as uploaded files, not yet
  read into anyone's report (see above).
- Nothing is sent to Anthropic, Claude, or anywhere outside this app.
