# Agentguard — Phases 01–09

Agentguard is a Python backend that plans tool use before execution, applies deterministic policy and provenance checks, detects and neutralizes suspected prompt injections, filters final answers, and records auditable runs. This package includes Phases 01–09: the defense core, OpenRouter client, JSON-backed mock agents, attacks and evaluation, an optional AgentDojo adapter, and a local FastAPI backend.

## What is included

- Phases 01–02: validated plan graphs, deterministic policy gate, provenance, scanner, neutralizer, output filter, executor, and offline `FakeLLM` tests.
- Phase 03: OpenRouter-only client, cached responses, persistent spend tracking, and a configurable spend cap.
- Phase 04: isolated JSON-backed email, Slack, and banking agents.
- Phases 05–07: 28 mock tasks, 14 attack patterns, 12 deterministic security goals, baselines, five-case evaluation batches, reports, and six demo scenarios.
- Phase 08: optional AgentDojo Track B adapter with fail-closed risk mapping, sink metadata, profile configuration, capped pair batching, and a subprocess entry point. AgentDojo is not required by the main environment.
- Phase 09: FastAPI endpoints for conversations, messages, runs, SSE event streaming, decisions, statistics, evaluation batches, mock data, and configuration; JSONL audit logs indexed in SQLite; log reindexing.

A Next.js App Router frontend is included in `frontend/` and connects to the Python API.

## Install and test

Requires Python 3.10 or newer.

```bash
cd backend
python -m venv .venv
# Windows PowerShell:
# .venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
```

Offline tests use `FakeLLM`; they do not need an API key. Copy `backend/.env.example` to `backend/.env` and set `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` only when you want real model calls. Never commit `.env`.

## Run the API

From `backend/`, after activating the virtual environment:

```bash
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

The API listens on localhost. It has no authentication in this demo configuration, so keep it bound to `127.0.0.1` and do not expose it to a public network. Open `http://127.0.0.1:8000/docs` for the interactive API reference.

Create a conversation and start an offline or OpenRouter-backed run using the API:

```bash
curl -X POST http://127.0.0.1:8000/api/conversations \
  -H 'Content-Type: application/json' -d '{"title":"Injection test"}'

curl -X POST http://127.0.0.1:8000/api/runs \
  -H 'Content-Type: application/json' \
  -d '{"command":"Summarize my unread emails","defense":"ours"}'
```

The run response contains a `run_id`. Subscribe to `/api/runs/{run_id}/stream` for SSE audit events, or inspect `/api/runs/{run_id}`, `/api/runs/{run_id}/events`, and `/api/decisions?decision=BLOCK`.

## Test with a malicious email

`backend/data/email.malicious.json` contains two ordinary emails and one clearly malicious test email. The clean benchmark fixture at `backend/data/email.json` is unchanged. To run the malicious message through the local API, back up the clean file, temporarily use the malicious fixture, start the API, and submit a request to summarize unread email:

```powershell
cd backend
Copy-Item .\data\email.json .\data\email.clean.backup.json
Copy-Item .\data\email.malicious.json .\data\email.json -Force
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

In another PowerShell window, submit `Summarize my unread emails` from the API docs at `http://127.0.0.1:8000/docs` (`POST /api/runs`, with `{"command":"Summarize my unread emails","defense":"ours"}`). Inspect the run's events at `GET /api/runs/{run_id}/events` for `INJECTION_SUSPECTED` and `INJECTION_NEUTRALIZED`. Restore the clean fixture after the test:

```powershell
Copy-Item .\data\email.clean.backup.json .\data\email.json -Force
Remove-Item .\data\email.clean.backup.json
```

You can verify the fixture's scanner and redaction behavior without an API key by running `python -m pytest tests/test_malicious_email_fixture.py` from `backend/`.

## Run the Phase 7 evaluator

Preview the first cases without making model requests:

```bash
cd backend
python -m eval.run_eval --suite all --mode attack_defended --attack all --include-heldout --batch-size 5 --dry-run
```

Run a five-case defended batch with OpenRouter:

```bash
python -m eval.run_eval --suite all --mode attack_defended --attack all --include-heldout --batch-size 5
```

Use `--reset-cursor` to start the batch sequence again. Each batch is capped at five cases unless the CLI's explicit cost confirmation options are used. Review case-level audit logs under `backend/logs/evals/runs/` and aggregate output in `backend/logs/evals/results.jsonl`.

## Phase 8: optional AgentDojo Track B

Track B uses its own virtual environment because the benchmark has additional dependencies. Install a compatible AgentDojo v1.1.2 source checkout into a separate environment, then install this backend there as well. Set `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` in that environment. The main backend does not import AgentDojo or its provider-specific model adapters.

```bash
cd backend
python -m venv .venv-agentdojo
# Activate the environment, then install this package and the external AgentDojo checkout.
python -m pip install -e '.[dev]'
python -m pip install -e /path/to/agentdojo-v1.1.2
python -m agentdojo_adapter.runner --suite banking --attack important_instructions --defense ours --batch-size 5 --offset 0
```

Pair sizes are capped at five per invocation. Track B requires the separate benchmark package and a configured OpenRouter key; it is not run by the offline test suite.

## Logs and reindexing

Audit JSONL files are the source of truth. SQLite at `backend/logs/index.db` provides run, event, decision, conversation, and evaluation indexes plus spend and cache data. Rebuild the searchable event index from the log files with:

```bash
cd backend
python -m core.logstore reindex --logs logs
```

The API also provides `POST /api/reindex`. API keys and prompt contents are not written to the UI configuration response. Prompt logging is off by default.

## Security behavior and limits

- Tool outputs remain untrusted data. The plan and deterministic gate control tool authority; the scanner and content neutralizer are additional defenses.
- The scanner is heuristic and can miss novel attacks or flag benign text. Deterministic provenance and gate checks are the primary action controls.
- Tool-output injection scanning combines known-pattern signatures with a semantic classifier call through the configured OpenRouter model for untrusted text that the signatures did not match. Classifier decisions are logged separately; they never authorize actions. Evaluator output reports injection detection separately from attack success, blocks, utility, and actual redactions. This adds model calls and cost when tool outputs contain text.
- If a user delegates a sensitive value to an attacker-controlled document without a trusted cross-check, the system may require confirmation or block the action.
- The planner can misunderstand a legitimate request. The graph validator and policy checks reduce, but cannot eliminate, that risk.
- The output filter checks for known grounding and exfiltration issues; it cannot prove that source documents are truthful.
- Mock-agent results are not directly comparable with external benchmark results. Track B results depend on benchmark setup, model, and prompts.

## Development

```bash
cd backend
python -m pytest
python -m demo.cli --scenario attack
python -m demo.scenarios
```

The Python API is a local demo service. With `INTERNAL_API_SECRET` configured,
it accepts API requests only from the authenticated Next.js gateway. Workspace
data is shared among signed-in users; per-user data isolation is not implemented.

## Agent workspace frontend

Open http://localhost:3000/ after starting both servers. The Next.js App Router
frontend opens to a public landing page. MiniMoth phone verification at `/login`
or `/signup` creates a session, then opens the protected `/dashboard`. React
components manage the screens, forms, preferences, and live execution updates.
The old http://localhost:8000/ app link redirects to the Next.js frontend.

The workspace includes agent runs with live SSE execution events, analytics,
Email/Slack/Banking agent tasks and mock data, injection scenarios, evaluation
batches, audit decisions, JSON exports, and browser-local execution preferences.
Next.js proxies `/api/*`, `/docs`, and `/openapi.json` to the Python backend,
including SSE streams. OpenRouter credentials stay in `backend/.env`; they are
never included in the browser bundle. Agent data is mock data, not live accounts.

For the Python environment prepared in this workspace:

```powershell
cd backend
.\.venv312\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

In a second terminal (Node.js 20.9 or newer):

```powershell
cd frontend
npm ci
npm run dev
```

For production, use `npm run build` followed by `npm start` instead of `npm run dev`.
Optionally set `BACKEND_URL` in `frontend/.env.local` when the Python server uses
a different address. Its default is `http://127.0.0.1:8000`. Set `FRONTEND_URL`
in the backend process environment to change its root redirect destination.

## Email Agent REST API (Frontend Reference)

The backend provides dedicated endpoints for building an interactive email agent UI:

- `GET /api/email/status`: Returns current operating configuration (`real` vs `mock`, `readonly`/`draft_only`/`full`, `dry_run`, `send_allowlist`), OAuth/IMAP auth status, and inbox counters (`unread`, `total`).
- `POST /api/email/config`: Live runtime configuration updater for frontend demo controls (`email_agent`, `mode`, `dry_run`, `send_allowlist`).
- `GET /api/email/inbox`: Lists mailbox emails (supports `unread_only=true`, `limit=25`, and search query `query=...`).
- `GET /api/email/messages/{email_id}`: Retrieves full normalized email payload.
- `POST /api/email/messages/{email_id}/read`: Marks an email as read.
- `DELETE /api/email/messages/{email_id}`: Trashes/deletes an email (respects mode and dry-run).
- `POST /api/email/draft`: Creates a draft email (`to`, `subject`, `body`).
- `POST /api/email/send`: Sends an email or simulates in dry-run mode (enforces recipient allowlist, live cap, and audit ledger).
- `GET /api/email/actions`: Retrieves all write operations logged to the `ActionLedger`.
- `DELETE /api/email/actions`: Clears the action ledger.
- `POST /api/email/run`: Executes a prompt specifically targeting the email agent through the complete security defense pipeline (`SecurityGate`, `Planner`, `Executor`, provenance and scanners).

The API is a local demo service, not a production deployment: it has no authentication, operational hardening, or multi-user isolation.

### MiniMoth authentication

Copy `frontend/.env.example` to `frontend/.env.local` and configure:

- `MINIMOTH_API_KEY`: your MiniMoth project key, used only by server code.
- `SESSION_SECRET`: an independent random value of at least 32 characters.
- `INTERNAL_API_SECRET`: a second independent random value; set the same value
  in `backend/.env` so direct Python API calls cannot bypass login.
- `APP_ORIGIN`: the exact public HTTPS origin when deploying behind a proxy.

Use `node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"`
to generate each secret separately. Keep both `.env` files out of Git.

MiniMoth uses WhatsApp/SMS phone OTP rather than email/password or Google login.
Phone sign-in requires an `mm_live_` MiniMoth project key for real WhatsApp or SMS OTP delivery. Sandbox keys are rejected; verification codes are never displayed in the app.

Session tokens are encrypted in an HttpOnly, SameSite cookie, with Secure set
on HTTPS. The gateway validates sessions server-side and rotates expired tokens
through MiniMoth. Workspace pages, API routes, and API documentation require
sign-in. Mutations reject cross-origin requests; sign-out revokes the provider
session and clears the local cookie. Do not expose the Python port publicly.

Run `npm test` in `frontend/` for local auth tests. With the app running, set
`AUTH_TEST_ORIGIN=http://localhost:3000` to also run anonymous-route and CSRF
integration checks. These tests do not send OTP messages. The sky image in
`frontend/public/hero-sky.png` comes from the user-supplied Runway reference.
