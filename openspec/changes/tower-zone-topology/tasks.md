## 1. Model: Tower.zones many-to-many

- [ ] 1.1 Add `Tower.zones` (many-to-many to `game.Zone`); keep the existing `Tower.zone` field temporarily so the data migration can read it.
- [ ] 1.2 Add the at-least-one-tower invariant to `Zone` (model `clean()` plus a guard that rejects removing a zone's last member link or deleting its last member tower).
- [ ] 1.3 Update `Tower.save()` autocreate-circle-zone: create the circular `Zone` and add it to `self.zones` (instead of setting a single `zone` FK) when `autocreate_zone` is set and the tower has no zones.

## 2. Migration off the single foreign key

- [ ] 2.1 Data migration: for every `Tower` with a non-null `zone`, add that zone to `tower.zones`; report any `Zone` that ends with zero member towers (do not delete it).
- [ ] 2.2 Follow-up schema migration: remove the `Tower.zone` field once no code references it.

## 3. Zone-control recompute code (implements the `Zone conquest rule` from `zone-conquest-and-scoring-config`)

- [ ] 3.1 Update `Tower.assign_to_team` to iterate `self.zones.all()`, recomputing conquest-rule control per zone per TeamGroup and opening/closing `TeamZoneOwnership` for each zone.
- [ ] 3.2 Update `Tower.unassign` to iterate `self.zones.all()`, closing/reopening zone ownerships per zone.
- [ ] 3.3 Count a zone's active member towers via the reverse many-to-many (`zone.tower_set` / related name) instead of `Tower.objects.filter(zone=...)`.
- [ ] 3.4 Resolve the relevant `TeamGroup`s from the Session/Game context rather than `zone.game` (removed by the foundation change).

## 4. APIs & serializers

- [ ] 4.1 Tower serializer exposes `zones` (a list of zone ids / nested zones) instead of a single `zone`.
- [ ] 4.2 Staff filters for towers and zones use the many-to-many membership.

## 5. Admin

- [ ] 5.1 Tower admin: show and filter by `zones` (many-to-many); make `zones` an editable multi-select; keep the autocreate-zone action adding to the set.
- [ ] 5.2 Zone admin: show member towers (list/count); block any save/delete that would drop the zone to zero member towers.

## 6. Frontend (staff)

- [ ] 6.1 Tower editor: multi-select `zones`; Zone editor: display member towers.

## 7. Tests

- [ ] 7.1 Migration test: each pre-existing single-zone tower resolves the identical zone membership and control outcome after migration.
- [ ] 7.2 Overlapping-zones test: a tower in two overlapping zones, on capture, recomputes majority control independently for each zone (a team may win one and not the other).
- [ ] 7.3 Invariant test: removing a zone's last member tower (or deleting its last member link) is rejected; a zone always retains at least one tower.
- [ ] 7.4 Logical-not-spatial test: a tower whose point lies outside a zone still contributes to that zone's control when linked, and a tower inside a polygon is never auto-added.
- [ ] 7.5 Unassign test: deactivating a tower closes/reopens zone ownerships across all of its zones.
