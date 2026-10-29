# FlowRank operations

## Runtime and storage

The production entrypoint is `app:app`, a Flask WSGI application on Vercel's Python runtime. `python app.py` uses Waitress locally. The original `python -m flowrank.server` is retained solely as the v1 educational example; it is not the product server.

Production requires `DATABASE_URL`. It fails closed if that variable is missing on Vercel. Local development defaults to SQLite. Each database operation runs in a short transaction with a fresh pooled PostgreSQL connection. Supavisor transaction pooling uses port 6543 and prepared statements are disabled. TLS is required by the provisioned URL.

The deployment uses the private `flowrank` schema within the existing DuetSync Supabase project, as authorized by the owner. It does not modify DuetSync tables or authentication settings. This shares physical database capacity; isolate into a dedicated project when capacity or compliance warrants it.

## Provision a separate environment

1. Create a PostgreSQL database or Supabase project and inspect it before applying `migrations/001_product.sql` once as an administrator.
2. Set a high-entropy password for `flowrank_runtime` using a secure administrator interface. Never commit credentials.
3. Seed `flowrank.videos` from `flowrank.catalog.seed_catalog(time.time())`. All bundled assets have been reviewed and enter as approved. New admin imports always enter as pending.
4. Set Vercel Production variables: `DATABASE_URL` (Secret), `COOKIE_SECURE=true` (Config), `ADMIN_TOKEN_HASH` (Secret; SHA-256 of a random admin token), and `CRON_SECRET` (Secret; random bearer credential). Retain the admin token in your secret manager.
5. Use a different database and credentials for preview/testing deployments. Production secrets are not provisioned for previews.
6. Link the intended Vercel team and project. Stage with `vercel deploy --prod --skip-domain`, inspect build logs and health, verify the release, then promote that exact deployment with `vercel promote URL`.

The optional `scripts/provision_vercel_env.py` helper reads ignored `.local` files and streams values into an authenticated Vercel CLI. It never contains embedded credentials. Its fixed team/project context is for this owner's deployment and must be adapted for a fork.

## Guest identity and authorization

Guest sessions use 256-bit random bearer tokens in Secure, HttpOnly, SameSite=Lax cookies. Only SHA-256 token hashes reach storage. A session lasts 30 days and cannot be recovered after cookies are cleared; it is not an email/password account or cross-device login.

The server derives the guest context from its cookie; it never trusts a user ID supplied in a URL or payload. Every PostgreSQL transaction sets a local `app.session_hash` context. Forced RLS restricts sessions, impressions and feedback to that context. The runtime login is neither superuser nor BYPASSRLS. No tables are exposed through PostgREST, and no SECURITY DEFINER functions or Supabase service keys are used. The trusted backend login can access the catalog and rate counters. Compromise of that server credential remains a security incident: RLS is defense in depth, not protection against a compromised app server setting its own tenant context.

State-changing API requests require a custom verification header and same-origin browser checks. No CORS wildcard is configured. SQL is parameterized; strings render through `textContent`. A restrictive CSP, nosniff, frame denial and HTTPS HSTS protect the served interface. Logs include request path, status, duration and request ID; they omit cookies, request bodies and raw IP addresses.

## Retention and privacy

`GET /api/maintenance` checks `Authorization: Bearer CRON_SECRET`. Vercel runs it daily at 08:00 UTC. Expired sessions cascade-delete their impressions and feedback. Stale rate counters expire after one day. PostgreSQL RLS includes narrowly scoped read/delete policies for already-expired sessions, allowing this job without a privileged maintenance credential.

`DELETE /api/privacy` deletes the caller's session immediately, including its impressions and feedback. It clears the cookie; the UI then starts a new empty session. `GET /api/privacy/export` exports only the current session's preferences, feedback, exposures, scores and feature snapshots. Personalization opt-out disables interest-based ranking; exposure and feedback logging still runs, as the dialog explains. Retention applies to the live database, not operator backups; configure backup retention separately before handling sensitive user data.

## Moderation and ingestion

Admin API access is disabled when `ADMIN_TOKEN_HASH` is blank. With an admin bearer token:

- `POST /api/admin/catalog` validates a metadata record and adds it as **pending**.
- `PATCH /api/admin/catalog/ID` accepts `pending`, `approved` or `blocked`.
- Public feed and impression endpoints admit approved content only.
- A viewer's hide/report excludes that item from their session; it does not automatically block it for everyone.

The demo accepts only reviewed media already packaged under `/static/media/`. It deliberately has no anonymous uploads or external URL fetcher. For user-generated content, add an object-storage upload flow, malware scanning, transcoding and a real human moderation queue before enabling uploads.

## Experiments and model changes

Guests receive a stable, hash-based 50/50 assignment to `balanced` or `diverse`. The diversity penalty differs between variants; impressions store the assignment, feature snapshot and score. This is experiment instrumentation, not proof of statistical benefit. Session-level assignment does not supply item-level propensity scores, so this release does not claim unbiased inverse-propensity evaluation.

Run `python -m scripts.train_product` to reproduce the synthetic artifact and ranking metrics. The temporal split holds the last 60 synthetic query groups out; no query appears in both partitions. Use `--exports path.json ... --output .local/candidate-model.json` for opted-in activity exports. Only explicitly labeled exposures enter training; silent non-engagement is not treated as a negative. Real data remains selection-biased, and a minimum of 100 labeled exposures is only a validity check, not evidence of adequacy. Review a candidate before replacing `flowrank/model.json` and deploying. There is no automatic feedback retraining.

## Verification and incidents

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
npm ci
npx playwright install chromium
python app.py
# In another terminal:
npm run test:e2e
```

For the optional direct database isolation test, set `DATABASE_TEST_URL` to a **test database** with the provisioned schema. The test creates and removes only its own random session rows. Tests must never run broad cleanup against a shared production database.

Check `/health` for DB connectivity and application version. It does not guarantee content availability, playback or performance. Use Vercel structured runtime logs to locate a failing request ID. Verify media requests return HTTP 200/206. Do not paste credentials into logs or GitHub issues. Roll back the Vercel deployment if needed; schema migrations require separate forward-compatible planning and are not undone by application rollback.

The release has functional and security integration coverage, not a sustained load test, independent penetration test, disaster-recovery drill, or availability SLA. Watch database connection saturation, error rates, latency, media bandwidth and rate-limit responses before increasing traffic.
