# IPIGuard — Phases 01–04: Protection, OpenRouter, and Mock Agents

This ZIP contains **Phases 01–04** of the attached plan. Phases 01–02 provide the deterministic protection layer and FakeLLM executor. Phase 03 adds the OpenRouter client, persistent budget ledger, and response cache. Phase 04 adds isolated JSON-backed email, Slack, and banking mock agents. It is a standalone Python package under `backend/` and is not a copy of the entire IPIGuard repository.

## Included

- Namespaced tool registry with risk, parameter schema, sink, and output-trust metadata.
- Pydantic plan schema, NetworkX DAG builder, and deterministic graph validator.
- Provenance classification against **raw** tool output.
- Policy gate implementing R1–R8, with human-readable explanations for every non-ALLOW decision.
- Heuristic injection scanner and a copy-only neutralizer (`off`, `annotate`, `redact`).
- Final-answer output filter implementing F1–F6, with structured decisions and raw-answer hash.
- Append-only, flushed JSONL audit writer with basic secret masking.
- Two-step planner with deterministic graph validation and retry handling.
- Unknown-argument resolver restricted to declared dependencies and their sanitized views.
- Constrained expansion, topological executor, gate-on-retry behavior, dependent skipping, and final-answer generation/filtering.
- Zero-cost scripted `FakeLLM`, offline terminal demo, and toy tools in tests.
- OpenRouter-only real client with JSON parsing/repair, bounded retries, usage and cost tracking, persistent spend guard, and temperature-zero response cache.
- SQLite tables for spend, eval cursors, and response cache; `.env.example` documents configuration.
- JSON-backed email, Slack, and banking agents with 27 registered tools, risk classes, schemas, sink metadata, trust metadata, snapshots, diffs, and per-case state isolation.
- Tests for graph, provenance, gate, scanner, neutralizer, output filtering, audit behavior, and end-to-end Phase 02 scenarios.

Phase 00 scaffolding is included: project metadata, test configuration, shared types, and `FakeLLM`. The API, UI, and evaluation harness are later phases.

## Run

Requires Python 3.10+.

```bash
cd backend
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux:
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
```

No API key, internet access, or model call is needed for tests. The code has no global mutable tool registry; instantiate `ToolRegistry` and `PolicyGate` per application/test.

## Phase 03: OpenRouter setup

Copy `backend/.env.example` to `backend/.env`, then set `OPENROUTER_API_KEY` and an `OPENROUTER_MODEL` id. Keep `MAX_BUDGET_USD` at or below `$4.00` to retain margin under the plan's `$5` total budget. Real calls are opt-in:

```bash
cd backend
python -m core.llm_check --no-tool-check
python -m core.llm_check
python -m demo.cli --scenario benign --openrouter
```

The full sanity check uses two small requests to verify JSON mode and native tool calling. The spend ledger is stored at `backend/logs/index.db`; identical temperature-zero requests are served from the SQLite cache at zero cost. Never commit `.env`.

## Phase 04: mock agents

Create a fresh environment for each task or evaluation case; it includes the trusted profile plus the three agent states:

```python
from agents import create_mock_environment, snapshot_diff

env = create_mock_environment(injections={"INJ_EMAIL_BODY_1": "untrusted test text"})
before = env.snapshot()
env.registry.require("email.list_inbox").fn(unread_only=True)
env.email.mark_read("e1")
changes = snapshot_diff(before, env.snapshot())
```

Each new `create_mock_environment()` loads fresh data from `backend/data/`; tools mutate only that environment's in-memory state.

## Minimal example

```python
from pydantic import BaseModel

from core.gate import GateContext, PolicyGate
from core.graph import PlanGraph, PlanNode
from core.registry import ToolRegistry, ToolSpec

class SearchArgs(BaseModel):
    query: str

registry = ToolRegistry([
    ToolSpec("email.search", "email", None, SearchArgs, "read",
             output_trust={"messages": "untrusted"}, description="Search email"),
])
node = PlanNode(id="1", function_name="email.search", args={"query": "invoice"})
plan = PlanGraph(nodes=[node])
decision = PolicyGate(registry).check(
    {"tool": node.function_name, "args": node.args}, node,
    GateContext(user_command="Find my invoice", plan=plan),
)
assert decision.action.value == "ALLOW"
```

See `backend/core/` and `backend/tests/` for module APIs and examples. Gate/output-filter decisions can be written with `JsonlAuditLog.decision()` and `.output_filter()`.

## Phase 02 demo (FakeLLM by default)

```bash
cd backend
python -m demo.cli --scenario attack
python -m demo.cli --scenario benign
```

The attack scenario shows the plan, the blocked write expansion with its reason, the output-filter action, the delivered answer, and deterministic Security notes. Both scenarios use `FakeLLM` by default; no API key or model spend is involved. Use `--openrouter` to run the same toy pipeline with the configured real model.

## Current limits

- Scanner patterns are heuristic. Structural plan membership, provenance checks, and deterministic gates are the primary controls.
- Provenance depends on callers registering accurate field trust and supplying raw upstream outputs.
- Delegated values remain a sensitive case; the gate can flag them, but a production confirmation or cross-check flow is not part of these phases.
- The output filter grounds values in the available request/profile/raw data. It cannot establish that a source document itself is truthful.
- Secret masking is best-effort; production audit retention and access controls are outside this phase.

## Differences from IPIGuard

- New tool calls are checked against the validated graph and deterministic policy gate; blocked calls report an honest reason.
- Per-tool risk classes, sink parameters, and output-trust metadata replace a global read-only whitelist.
- Expansion is proposed through a bounded interface and every proposed call is gated.
- Resolver prompts receive only declared upstream outputs, in sanitized form; no raw message history is sent.
- JSONL audit events record gate decisions, suspected injections, neutralization, and answer filtering.
- Provenance checks cover resolved sensitive arguments, including values filled inside an already-planned call.
- Final answers pass a deterministic output filter for links, active content, grounding, action claims, and secrets.
- The Phase 02 executor, toy tools, and tests are a new implementation; no upstream source files are copied.

See `NOTICE` for attribution and the upstream paper citation.
