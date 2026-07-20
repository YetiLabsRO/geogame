## Context

In the shipped model `game.Tower` carries a single nullable `zone` foreign key (`game/models.py`). The majority-rule recompute in `Tower.assign_to_team` and `Tower.unassign` is written around that single zone: it counts `Tower.objects.filter(zone=self.zone, is_active=True)`, iterates `TeamGroup.objects.filter(game=self.zone.game)`, and opens/closes exactly one zone's `TeamZoneOwnership`. The admin's autocreate-circle-zone hook in `Tower.save()` sets `self.zone` to a freshly buffered circle when the field is empty and `autocreate_zone` is set.

The `points-repository-and-collections` foundation change moved geometry into a reusable repository grouped by `Collection`s and removed the mandatory `game` FK from `Tower`/`Zone`, but it deliberately left the `Tower.zone` single-FK → many-to-many conversion to this change. This change completes the topology work: a tower can belong to multiple, possibly overlapping zones.

## Goals / Non-Goals

**Goals:**
- A tower can belong to several zones at once; zones can overlap and share towers.
- Zone control (majority/conquest) and zone-ownership recompute run correctly across all of a tower's zones, evaluating each zone independently.
- Every zone has at least one member tower (a validated invariant).
- Membership is logical, not spatial — never inferred from geometry.
- Zero data loss migrating each single-FK link into one many-to-many row; single-zone towers behave identically after migration.

**Non-Goals:**
- Specifying how zone control is computed. The conquest rule (ALL / MAJORITY / ANY), recomputing across every zone a tower belongs to, and evaluating overlapping zones independently are all owned by the `zone-conquest-and-scoring-config` change's `Zone conquest rule` requirement (authored topology-aware so it holds for one zone or many). This change carries **no `scoring` spec delta** — it supplies the many-to-many model and the code that implements that rule, avoiding a REMOVE-vs-MODIFY collision on the shipped `scoring` → "Majority-rule zone control" requirement.
- Spatial auto-assignment of towers to zones by polygon containment — membership stays explicit.
- Repository / Collection restructuring — delivered by `points-repository-and-collections`.

## Decisions

- **Replace `Tower.zone` FK with `Tower.zones` M2M** (Django's default auto through-table to `game.Zone`). Alternative considered: keep the FK and add a parallel M2M for "extra" zones — rejected because two sources of truth for membership drift and every recompute path would branch.
- **Membership is logical, not spatial.** The link is an explicit set operation and is never derived from point-in-polygon tests. Rationale: many game modes want a tower to score for a themed/overlay zone it is not physically inside, and once zones overlap, geometric containment is ambiguous anyway. Auto-inference would surprise authors and couple membership to floating-point geometry.
- **Recompute iterates `tower.zones.all()`** and, per zone, counts that zone's active member towers via the reverse many-to-many. Each overlapping zone is evaluated independently per TeamGroup, exactly the way a single zone is evaluated today, so a team can control one overlapping zone but not another.
- **TeamGroup source moves off `zone.game`.** The foundation removed `Zone.game`, so the recompute resolves the relevant TeamGroups from the Session/Game context rather than `self.zone.game`. A parity test asserts identical control outcomes for single-zone towers.
- **The at-least-one-tower invariant is enforced at the application layer** (model `clean()` plus API and admin validation), not as a database constraint, because minimum-cardinality on a many-to-many cannot be expressed as a simple DB constraint. Alternative considered: a Postgres trigger — rejected as heavyweight and fragile to maintain.
- **Autocreate-circle-zone adds to the set.** When a tower is saved with `autocreate_zone` and no zones, the save hook creates the circular Zone and adds it to the tower's `zones`, making the tower that zone's founding member — which also satisfies the at-least-one-tower invariant from creation.

## Risks / Trade-offs

- [Recompute now loops zones × groups, so a tower in many overlapping zones costs more work per capture] → bounded by realistic zone counts per tower; the through-table membership is indexed, so member-tower counts stay cheap.
- [A zone could be emptied to zero towers by removing its last membership or deleting its last member tower] → the at-least-one-tower invariant rejects any operation that would empty a zone; the data migration reports (rather than silently deletes) any pre-existing empty zone so staff can fix it.
- [Existing code reads `tower.zone` (singular) across models, admin, and serializers] → a codemod pass repoints reads to `tower.zones`; the data migration plus a parity test cover single-zone behavior.
- [The foundation and this change both restate the same `geographic-map` requirements] → this change's restatements build on the foundation's post-change text (repository/Collection framing) so the two are forward-consistent when archived in order.

## Migration Plan

1. Add `Tower.zones` (many-to-many to `game.Zone`), initially empty, alongside the still-present `Tower.zone`. Schema migration.
2. Data migration: for every `Tower` with a non-null `zone`, add that zone to `tower.zones`. Report any `Zone` left with zero member towers (do not delete it) so staff can attach a tower or remove the zone.
3. Repoint recompute, admin, and serializer code from `tower.zone` (singular) to `tower.zones` (iterate); count a zone's member towers via the reverse many-to-many; resolve TeamGroups from the Session/Game context.
4. Follow-up schema migration: remove the `Tower.zone` field once no code references it.
5. Verify parity: a single-zone tower resolves the identical zone membership and produces the identical control outcomes it did before migration (regression test).
