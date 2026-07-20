## Why

Today `Tower.zone` is a single nullable foreign key: a tower belongs to at most one zone, and majority/conquest zone control assumes each tower contributes to exactly one zone. Many desired game modes need overlapping zones and towers that count toward several zones at once — for example a landmark that belongs to both a geographic district and a themed overlay, or nested "inner/outer" zones that share the same objectives. This change makes tower–zone membership many-to-many, permits zones to overlap and share towers, and adds the invariant that every Zone has at least one Tower. The link is deliberately **logical, not spatial**: a tower does not have to sit geographically inside a zone it belongs to.

## What Changes

- Replace `Tower.zone` (single nullable FK) with `Tower.zones` (many-to-many to `game.Zone`). A tower MAY belong to zero, one, or many zones; zones MAY overlap and share towers.
- State explicitly that the tower–zone link is **logical, not spatial** — membership is an explicit set operation and is never inferred from point-in-polygon geometry, so a tower need not be inside its zone(s).
- Add the invariant: every `Zone` SHALL have at least one member `Tower`.
- Update the zone-control recompute code (the `Tower.assign_to_team` and `Tower.unassign` paths) to iterate over **every** zone a tower belongs to, evaluating each zone independently per TeamGroup. The *specification* of how zone control is computed (the ALL/MAJORITY/ANY conquest rule, recomputed across a tower's zones, overlapping zones evaluated independently) is owned by the `zone-conquest-and-scoring-config` change's `Zone conquest rule` requirement; this change provides the many-to-many model that rule operates over and the code that implements it.
- Update admin: Tower admin lists/filters by `zones` (many-to-many); Zone admin surfaces member towers and guards the at-least-one-tower invariant; the autocreate-circle-zone behavior adds the new circular zone to the tower's `zones` set instead of setting a single FK.
- Migration: convert each existing non-null `Tower.zone` into one `Tower.zones` row, then drop the `zone` field.

## Capabilities

### New Capabilities

<!-- None -->

### Modified Capabilities

- `geographic-map`: `Tower.zone` single FK becomes `Tower.zones` many-to-many; overlapping zones and shared towers are allowed; membership is logical, not spatial; every zone has at least one tower.
- `admin-operations`: zone/tower admin screens and the autocreate-circle-zone behavior are updated for many-to-many membership and the at-least-one-tower invariant.

**Not modified here (delegated):** the zone-control computation itself — recomputing across a tower's zones and evaluating overlapping zones independently — is specified by the `zone-conquest-and-scoring-config` change's `Zone conquest rule` requirement (written topology-aware so it holds for one zone or many). This change carries no `scoring` spec delta; it supplies the many-to-many model and the code that implements that rule. Reconciled to avoid a REMOVE-vs-MODIFY collision on the shipped `scoring` → "Majority-rule zone control" requirement.

## Impact

- **Models**: `game.Tower.zone` (FK) → `game.Tower.zones` (M2M to `game.Zone`, default through-table); the zone-control recompute in `Tower.assign_to_team` / `Tower.unassign` iterates `tower.zones` and counts a zone's active member towers via the reverse M2M; `Zone` gains at-least-one-tower validation.
- **APIs**: tower serializers expose `zones` (a list) instead of a single `zone`; staff tower/zone filters switch to the many-to-many membership.
- **Frontend**: the staff tower editor picks multiple zones (multi-select); the zone editor shows its member towers.
- **Migrations/other**: a data migration copies each `Tower.zone` into `Tower.zones` and reports any zone left with zero towers, followed by a schema migration removing `Tower.zone`; the admin autocreate-zone save hook is updated.
