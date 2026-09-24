## Context

The `points-repository-and-collections` foundation establishes the authoring model: a **creator** authors a `Game` (template) that references reusable `Collection`s of `Tower`s and `Zone`s, owns a `Challenge` bank, a `TeamGroup` taxonomy, per-game roles, and a large config surface (scoring units, zone-conquest rule, proximity, visibility, locking, and more added by sibling changes). Authoring all of that by hand is slow. An LLM given a town's context can draft it, but must (a) see the **available options** to stay valid, and (b) be prevented from writing unreviewed content. MCP (Model Context Protocol) is the natural interface: an LLM host connects to a server that publishes typed tools. The design question is how to expose a *full* surface while keeping every write **curated** — suggested by the model, approved by a human, applied only within the creator's own permissions.

## Goals / Non-Goals

**Goals:**
- One MCP server exposing read/discovery tools over every game element and the config schema, so an LLM can compose a new game only from valid, available options.
- A suggest-only write surface: LLM tool calls **stage** operations, they never write live.
- A staged change-set (`AuthoringProposal` of ordered `ProposedOperation`s) with temp refs so multi-object drafts (new Collection + its new Towers + their Challenges) stage as one reviewable unit.
- A strict **human approval gate**: nothing is applied without an authorized person approving; the LLM cannot self-approve.
- Every apply runs **within the creator's scope**, re-checking permissions at apply time (never escalating).
- A complete, append-only **audit trail** of what the LLM proposed, why, who approved it, and what was written.

**Non-Goals:**
- Defining the config knobs themselves — those are owned by `game-configuration`, `scoring`, `tower-visibility`, `tower-locking`, `score-multipliers`, etc. This change only *reflects* their schema.
- A general write API for humans — creators keep using the existing staff/creator REST API and (later) `field-authoring-mode`. This is only the LLM-mediated path.
- Autonomous/agentic apply. No "auto-approve" mode ships; approval is always an explicit human act.
- Model hosting or prompt engineering. The LLM/host lives on the client side of MCP; the server only publishes tools and enforces the gate.

## Decisions

- **New `authoring` Django app.** Keeps MCP transport, staging models, and the apply engine separate from `game` (geometry/scoring) and `organize` (accounts/sessions). Alternative considered: fold into `organize` — rejected because the MCP server, its SDK dependency, and the audit log are a distinct concern that shouldn't bloat the accounts app.
- **Writes are staging-only, enforced server-side — not by tool naming.** Every `propose_*` tool constructs `ProposedOperation` rows on an `AuthoringProposal`; none call the real model managers. The apply engine is the *only* code path that mutates real Collections/Towers/Zones/Challenges/Games/roles/config, and it runs only after a human approval. Alternative considered: give the LLM the real staff REST API with a "dry-run" flag — rejected because a single missing flag would write live; the safe design has no live-write code path reachable from MCP.
- **Reuse the existing service/serializer layer for both read and apply.** Read tools serialize through the same DRF serializers the staff API uses (consistent shapes, one source of truth). The apply engine validates each operation's payload through the corresponding serializer and calls the same create/update logic, so the LLM path can never produce records the human API couldn't. Alternative considered: a parallel write layer — rejected as drift-prone.
- **Creator-scoped credential, not a shared service account.** An `McpCredential` is a hashed bearer token bound to one `User` (a creator). The MCP session authenticates as that user; every read is filtered and every staged/applied write is authorized exactly as if that creator made it. Alternative considered: one privileged MCP service user — rejected because it would bypass per-creator scoping and pollute the audit trail's actor identity.
- **Temp refs for intra-proposal dependencies.** A `ProposedOperation` targets either an existing object (by PK, for updates/links) or a client temp ref like `@new:collection-1` (for creates). Apply resolves temp refs to real PKs in a topological order so a proposed Tower can be linked to a proposed Collection created earlier in the same proposal.
- **Approval granularity: per-operation and whole-proposal.** A reviewer may approve the whole proposal or cherry-pick operations. Rejected operations are skipped at apply; approved ones apply. This supports "the challenge ideas are great but drop the two zones" without a round-trip. Alternative considered: all-or-nothing — rejected as too coarse for curation.
- **Apply is transactional with partial-apply semantics.** Approved operations apply inside a DB transaction in dependency order. If an operation fails validation or permission at apply time, it is marked `FAILED` with the error; the proposal becomes `PARTIALLY_APPLIED` and the failure is recorded rather than silently dropped. Whether the transaction rolls back fully or commits successful-prefix is a per-proposal `atomic` flag (default: atomic — all-or-nothing on error, so the creator never gets a half-built map by surprise).
- **Audit trail is append-only and immutable.** `AuthoringAuditEvent` rows are never updated or deleted; each records actor (creator user + LLM/client identity + model id when the host provides it), event type (tool call, proposal transition, approval decision, apply outcome), a redacted argument/result summary, and a timestamp. The per-operation `rationale` (the LLM's stated reason) is stored on the operation and echoed into the audit event so reviewers see *what* and *why*.
- **MCP transport on the ASGI stack.** The server is mounted as a streamable-HTTP MCP endpoint on the same ASGI app that hosts Channels (adopted elsewhere in this batch), avoiding a second process. Alternative considered: a standalone MCP process calling the DRF API over HTTP — viable, but doubles auth surface and latency; kept as a fallback deployment option.

## Risks / Trade-offs

- [An LLM stages a large, plausible-but-wrong batch and a reviewer rubber-stamps it] → per-operation diff + rationale in the review UI, sane default of atomic apply, and the audit trail make review and rollback-by-review tractable; nothing is applied without an explicit human click.
- [Permissions change between stage and apply (creator loses access to a Collection)] → apply re-authorizes every operation as the creator at apply time; operations that no longer pass are `FAILED`, never force-applied.
- [Temp-ref graphs with cycles or dangling refs] → the apply engine topologically sorts operations and rejects a proposal whose refs are cyclic or unresolved *before* writing anything.
- [MCP credential leakage grants an attacker the LLM surface] → credentials are hashed at rest, revocable, scoped to one creator, and — crucially — the surface is suggest-only, so a stolen token can stage proposals but cannot apply anything without the human gate; all staging is audited.
- [Config schema drift as sibling changes add knobs] → the config-schema read tool is generated from the live serializer/model field definitions, not hand-maintained, so new knobs appear automatically.
- [Serializer reuse couples MCP apply to staff-API validation changes] → acceptable and intended: one validation source of truth; covered by tests that a stitched proposal produces the same records the staff API would.

## Migration Plan

1. Create the `authoring` app; add `McpCredential`, `AuthoringSession`, `AuthoringProposal`, `ProposedOperation`, `AuthoringAuditEvent`; run migrations. No existing tables change.
2. Add the `mcp` Python SDK to `requirements.txt`; mount the MCP endpoint on the ASGI app behind credential auth.
3. Implement read/discovery tools over the existing serializers and a generated config schema.
4. Implement suggest/stage write tools that only append `ProposedOperation`s.
5. Implement the approval + apply engine (temp-ref resolution, per-op authorization, transactional apply, partial-apply/audit).
6. Add the DRF review endpoints and the staff-SPA review inbox + credential management.
7. Ship with no auto-approve path; document the human-in-the-loop workflow. No data backfill is required (all models are new and start empty).
