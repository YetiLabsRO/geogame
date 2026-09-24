## Why

Authoring a good game is the hard part: a creator has to invent Collections, drop Towers and Zones, write a Challenge bank tuned to a specific town, define per-game roles, and set dozens of config knobs to sensible values. An LLM that already knows a town's landmarks, history, and points of interest could do most of the first draft — but only if it can see the **available options** (which config enums exist, which Collections and geometry are already in the repository, what a Challenge looks like) and can **push proposed content in**. Letting an LLM write live to the database is unacceptable: it would author unreviewed, possibly wrong, possibly out-of-scope game content. This change adds an **MCP authoring server** that gives an LLM a full read surface over every game element and a **suggest-only** write surface: the LLM stages proposals, a human creator approves them, and only then are they applied — always within that creator's own permission scope, with a complete audit trail of what the LLM proposed and why.

## What Changes

- Add a new Django `authoring` app hosting the MCP server and its staging models.
- Expose an **MCP server** (Model Context Protocol) that an LLM client connects to, authenticated by a **creator-scoped** MCP credential that maps to exactly one Django user.
- **Read/discovery tools** over the full authoring surface: Collections, Towers, Zones, Challenges, Games (templates), TeamGroups, per-game roles, and a machine-readable **config schema** (knobs, enums, defaults) — so the LLM builds new games only from valid, available options (see the `collections`, `geographic-map`, `challenges`, `game-configuration`, and `team-roles` capabilities).
- **Suggest/stage write tools** (`propose_collection`, `propose_tower`, `propose_zone`, `suggest_challenge`, `propose_game`, `propose_game_role`, `propose_config`, `propose_link`, …) that never touch real models — they append operations to a staged `AuthoringProposal`. The LLM takes what it knows about a town and stages Challenge ideas (with a rationale) plus the supporting geometry and config.
- A **staged change-set model**: `AuthoringProposal` holds ordered `ProposedOperation`s (create/update/link), with client-side temp refs so a proposed Tower can reference a proposed Collection before either exists.
- A **suggest → stage → approve → apply** lifecycle. Approval is a **human** action in the staff app; the LLM/MCP can never self-approve. On approval the engine applies staged operations transactionally, in dependency order, **within the creator's scope**, re-checking permissions at apply time.
- An **append-only audit trail** (`AuthoringAuditEvent`) of every tool call, proposal state transition, approval decision, and apply outcome — capturing the LLM/client identity, model id, and the per-operation rationale.
- Staff API + staff-SPA "AI authoring review" inbox to review pending proposals (per-operation diff + rationale), approve/reject per operation or whole, withdraw, and see apply results.

## Capabilities

### New Capabilities
- `mcp-authoring`: an MCP server exposing a full read surface plus a suggest-only, staged, human-approved write surface over every game element, with creator-scoped permissions and an audit trail of what the LLM proposed.

### Modified Capabilities
<!-- None — this is a purely additive backend capability. It reads from and (on approval) writes through the existing authoring capabilities but does not change their shipped behavior. -->

## Impact

- **Models**: new `authoring` app with `authoring.McpCredential` (creator-scoped token), `authoring.AuthoringSession` (an LLM conversation/context, optional grouping), `authoring.AuthoringProposal` (staged change set + lifecycle state), `authoring.ProposedOperation` (one staged create/update/link with payload + rationale + temp ref), and `authoring.AuthoringAuditEvent` (append-only log). No changes to existing models.
- **APIs**: a mounted MCP endpoint (streamable-HTTP, e.g. `/mcp/authoring/`) authenticated by MCP credential; DRF review endpoints `GET /api/staff/authoring/proposals/`, `GET .../{id}/`, `POST .../{id}/approve/`, `POST .../{id}/reject/`, `POST .../{id}/operations/{op}/approve|reject/`, `POST .../{id}/apply/`, `POST .../{id}/withdraw/`, and `GET /api/staff/authoring/audit/`.
- **Frontend**: staff SPA gains an "AI authoring review" inbox (pending proposals, per-operation rationale + diff, approve/reject/withdraw, apply results); a screen to issue/revoke MCP credentials.
- **Migrations/other**: new app + migrations; add the `mcp` Python SDK to `requirements.txt`; the MCP server runs on the ASGI stack (shared with Channels); all writes route exclusively through the staging + approval + apply engine — there is no live-write path for the LLM.
