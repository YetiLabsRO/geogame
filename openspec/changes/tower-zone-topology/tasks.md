## 1. Model: Tower.zones many-to-many

- [x] 1.1 Add `Tower.zones` (many-to-many to `game.Zone`); keep the existing `Tower.zone` field temporarily so the data migration can read it.
- [x] 1.2 Add the at-least-one-tower invariant to `Zone` (model `clean()` plus a guard that rejects removing a zone's last member link or deleting its last member tower).
- [x] 1.3 Update `Tower.save()` autocreate-circle-zone: create the circular `Zone` and add it to `self.zones` (instead of setting a single `zone` FK) when `autocreate_zone` is set and the tower has no zones.

## 2. Migration off the single foreign key

- [x] 2.1 Data migration: for every `Tower` with a non-null `zone`, add that zone to `tower.zones`; report any `Zone` that ends with zero member towers (do not delete it).
- [x] 2.2 Follow-up schema migration: remove the `Tower.zone` field once no code references it.

## 3. Zone-control recompute code (implements the `Zone conquest rule` from `zone-conquest-and-scoring-config`)

- [x] 3.1 Update `Tower.assign_to_team` to iterate `self.zones.all()`, recomputing conquest-rule control per zone per TeamGroup and opening/closing `TeamZoneOwnership` for each zone.
- [x] 3.2 Update `Tower.unassign` to iterate `self.zones.all()`, closing/reopening zone ownerships per zone.
- [x] 3.3 Count a zone's active member towers via the reverse many-to-many (`zone.tower_set` / related name) instead of `Tower.objects.filter(zone=...)`.
- [x] 3.4 Resolve the relevant `TeamGroup`s from the Session/Game context rather than `zone.game` (removed by the foundation change).

## 4. APIs & serializers

- [x] 4.1 Tower serializer exposes `zones` (a list of zone ids / nested zones) instead of a single `zone`.
- [x] 4.2 Staff filters for towers and zones use the many-to-many membership.

## 5. Admin

- [x] 5.1 Tower admin: show and filter by `zones` (many-to-many); make `zones` an editable multi-select; keep the autocreate-zone action adding to the set.
- [x] 5.2 Zone admin: show member towers (list/count); block any save/delete that would drop the zone to zero member towers.

## 6. Frontend (staff)

- [x] 6.1 Tower editor: multi-select `zones`; Zone editor: display member towers.

## 7. Tests

- [x] 7.1 Migration test: each pre-existing single-zone tower resolves the identical zone membership and control outcome after migration.
- [x] 7.2 Overlapping-zones test: a tower in two overlapping zones, on capture, recomputes majority control independently for each zone (a team may win one and not the other).
- [x] 7.3 Invariant test: removing a zone's last member tower (or deleting its last member link) is rejected; a zone always retains at least one tower.
- [x] 7.4 Logical-not-spatial test: a tower whose point lies outside a zone still contributes to that zone's control when linked, and a tower inside a polygon is never auto-added.
- [x] 7.5 Unassign test: deactivating a tower closes/reopens zone ownerships across all of its zones.

## Implementation notes

Implemented together with `zone-conquest-and-scoring-config` on branch
`impl/zone-conquest-and-topology` (this change supplies the M2M model and
the topology-aware recompute; the conquest rule itself is that change's
spec delta).

- **Model**: `Tower.zones = ManyToManyField(Zone, related_name='towers')`.
  The recompute (`Tower._recompute_zones_control`) iterates
  `self.zones.all()` and evaluates each zone independently per TeamGroup
  over `zone.towers.filter(is_active=True)`; TeamGroups resolve via
  `TeamGroup.objects.filter(game__collections__zones=zone)` (the
  foundation removed `Zone.game`).
- **Migrations**: `game/0027_tower_zones_m2m` (add M2M),
  `game/0028_copy_tower_zone_to_zones` (data: copy each single FK link
  into one through-row; prints — never deletes — zones left with zero
  members), `game/0029_remove_tower_zone_fk` (drop the legacy FK).
- **Invariant enforcement** is three-layered: `Zone.clean()` (form
  validation), an `m2m_changed` guard on `Tower.zones.through`
  (pre_remove/pre_clear from either side), and a `pre_delete` guard on
  Tower. IMPORTANT: Django wraps m2m writes and deletes in
  `atomic(savepoint=False)`, so a raise from these signals poisons any
  enclosing transaction. Every call site that catches the error wraps
  the operation in its own `transaction.atomic()` savepoint: the DRF
  tower serializer `update()` / viewset `perform_destroy()`, and the
  Django admin `delete_model`/`delete_queryset`. The Tower admin also
  has a `TowerAdminForm.clean_zones` that rejects last-member removal at
  form-validation time (friendly error instead of a signal blow-up).
  Deleting a *Zone* is allowed — the invariant constrains emptying a
  zone, not removing it.
- **Autocreate-circle-zone** moved to `Tower.ensure_autocreated_zone()`,
  called from `Tower.save()` (post-insert, since M2M needs a pk) and
  re-run by `TowerAdmin.save_related` because the admin's `save_m2m`
  resets membership after `save()`. The created zone joins the tower's
  collections so it stays reachable by the same Games.
- **Serializers**: player `TowerSerializer` and staff
  `AdminTowerSerializer` expose `zones` (id lists; `zone` removed); the
  staff zone serializer lists member towers. Staff filters:
  `/api/staff/towers/?zone=<id>` and `/api/staff/zones/?tower=<id>`.
  `ZoneViewSet` (player) recomputed its ≥1-active-tower annotation over
  the M2M (`Count('towers', filter=...)`).
- Legacy dead files: `game/fixtures/tower_zones.json` still references
  the old `geogame.tower` model label and the removed `zone` field — it
  was unloadable before this change and was left untouched.
- Task 7.1's "control outcome identical" half is covered by the
  pre-existing `ZoneRecalculationTest` suite passing unchanged on the
  new engine; the data-migration half by `TowerZonesDataMigrationTest`.
- **Merge-conflict hotspots**: `game/models.py` (Tower/Zone bodies +
  signal guards), `game/admin.py`, `game/admin_api.py`,
  `game/tests.py` (`_make_tower` helper now links zones via M2M),
  `frontend/projects/staff/src/app/admin/towers.component.ts` /
  `zones.component.ts`, `frontend/projects/shared/src/lib/staff-api.service.ts`
  and `game-api.service.ts` (`TowerFeature.zones`).
