## 1. Authoring app, credentials & audit

- [x] 1.1 Create the `authoring` Django app; register in settings; wire migrations.
- [x] 1.2 Add `authoring.McpCredential` (hashed token, `created_by` creator FK, label, `is_active`, `last_used_at`, `revoked_at`); issue/verify/revoke helpers.
- [x] 1.3 Add `authoring.AuthoringSession` (creator FK, optional `target_game` FK, `client_name`, `llm_model`, `started_at`) grouping one LLM conversation for audit.
- [x] 1.4 Add `authoring.AuthoringAuditEvent` (append-only: session/creator FK, `event_type`, `tool_name`, redacted `args`/`result` JSON, `created_at`) with insert-only manager (no update/delete).

## 2. Staged change-set model

- [x] 2.1 Add `authoring.AuthoringProposal` (session FK, `created_by`, `status` DRAFT/PENDING/APPROVED/APPLIED/PARTIALLY_APPLIED/REJECTED/WITHDRAWN/FAILED, `atomic` flag, `summary`, timestamps, `decided_by`/`decided_at`).
- [x] 2.2 Add `authoring.ProposedOperation` (proposal FK, `entity_type` COLLECTION/TOWER/ZONE/CHALLENGE/GAME/GAME_ROLE/CONFIG, `action` CREATE/UPDATE/LINK/UNLINK, `target_ref` (existing PK or `@new:` temp ref), `payload` JSON, `rationale` text, per-op `status`, `applied_object_type`/`applied_object_id`, `error`, `order`).
- [x] 2.3 Temp-ref resolver + topological ordering; reject cyclic or unresolved refs before any write.

## 3. MCP server: read/discovery tools

- [x] 3.1 Mount a streamable-HTTP MCP endpoint on the ASGI app; authenticate the MCP session from the `McpCredential` bearer token and bind it to the creator user.
- [x] 3.2 Read tools `list_collections`/`get_collection`, `list_towers`, `list_zones`, `list_challenges`, `list_games`/`get_game`, `list_team_groups`, `list_game_roles` — all creator-scoped, serialized through the existing staff serializers.
- [x] 3.3 `describe_config_schema` tool: generate the config knob catalog (names, types, enums, defaults, docs) from live model/serializer field definitions, not a hand-maintained list.
- [x] 3.4 Record every tool call as an `AuthoringAuditEvent`.

## 4. MCP server: suggest/stage write tools

- [x] 4.1 `propose_collection`, `propose_tower`, `propose_zone`, `propose_game`, `propose_game_role`, `propose_config`, `propose_link` — each appends a `ProposedOperation` to the caller's open proposal; none touch real models.
- [x] 4.2 `suggest_challenge`: stage a proposed Challenge (text, difficulty, tower/generic binding, target Game) with a required `rationale`; support batching several suggestions in one call.
- [x] 4.3 Proposal-management tools `open_proposal`, `get_proposal`, `list_my_proposals`, `stage_operation`, `withdraw_proposal`, `submit_for_approval`.
- [x] 4.4 Reject at stage time any operation whose target is outside the creator's authoring scope (record the rejection in the audit trail).

## 5. Approval & apply engine

- [x] 5.1 Server-side approval API: whole-proposal and per-operation approve/reject; only an authorized human (creator or authorized collaborator) may decide; the MCP/LLM path can never approve.
- [x] 5.2 Apply engine: resolve temp refs in dependency order; re-authorize each operation as the creator at apply time; validate each `payload` through the corresponding serializer; call the same create/update logic as the staff API.
- [x] 5.3 Transactional apply with the `atomic` flag; on failure mark the op `FAILED` with the error and set the proposal `PARTIALLY_APPLIED` (or roll back when atomic); record `applied_object` refs on success.
- [x] 5.4 Emit `AuthoringAuditEvent`s for every state transition, approval decision, and apply outcome.

## 6. Proposal review API

- [x] 6.1 `GET /api/staff/authoring/proposals/` and `GET .../{id}/` returning per-operation diff (proposed vs current) + rationale, creator-scoped.
- [x] 6.2 `POST .../{id}/approve|reject|apply|withdraw/` and `POST .../{id}/operations/{op}/approve|reject/`.
- [x] 6.3 `GET /api/staff/authoring/audit/` exposing the append-only trail, filterable by proposal/session/creator.
- [x] 6.4 MCP credential management endpoints: issue, list, revoke (creator-scoped).

## 7. Staff SPA review UI

- [x] 7.1 "AI authoring review" inbox: pending proposals with summary, source LLM/model, and count of operations.
- [x] 7.2 Proposal detail: per-operation rationale + diff, approve/reject per operation or whole, withdraw, and apply-result display.
- [x] 7.3 MCP credential screen: issue and revoke creator-scoped tokens.

## 8. Tests

- [x] 8.1 Auth/scope tests: an `McpCredential` binds the MCP session to its creator; read tools return only that creator's authorable elements; out-of-scope reads/stages are denied.
- [x] 8.2 No-live-write test: every `propose_*`/`suggest_*` tool leaves real Collection/Tower/Zone/Challenge/Game/role/config tables unchanged until apply.
- [x] 8.3 Human-gate test: an approved-then-applied proposal writes records; an unapproved proposal cannot be applied; the MCP path cannot self-approve.
- [x] 8.4 Temp-ref/apply test: a proposal creating a Collection + Towers + Challenges applies in dependency order and links correctly; cyclic/unresolved refs are rejected before any write.
- [x] 8.5 Partial-apply test: per-operation approve/reject applies only approved ops; a failing op marks `FAILED` and sets `PARTIALLY_APPLIED` (or rolls back when atomic).
- [x] 8.6 Parity test: a stitched proposal produces the same records the staff API would for the same payloads (serializer reuse).
- [x] 8.7 Audit test: every tool call, transition, approval decision, and apply outcome is recorded append-only with actor + LLM identity + rationale, and events are never mutated/deleted.
- [x] 8.8 Re-authorization test: a creator who loses access to a Collection between stage and apply has the affected operations fail at apply, never force-applied.
- [x] 8.9 Coverage ≥80% on the `authoring` app; ruff-clean; single quotes.
