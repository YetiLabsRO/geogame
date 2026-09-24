# Tasks — tower types and styling

## 1. Model

- [x] 1.1 `game.TowerType`: `name`, unique `slug`, `icon` (Bootstrap Icons class name), `color`, nullable `proximity_meters`, `description`, `order`. Migration. Migration `0041_towertype_tower_color_tower_icon_tower_tower_type`.
- [x] 1.2 `Tower.tower_type` nullable FK (`on_delete=SET_NULL`, related_name `towers`); nullable `icon` and `color` overrides. Same migration.
- [x] 1.3 Documented untyped defaults as module constants, not literals scattered at call sites. `DEFAULT_TOWER_ICON` / `DEFAULT_TOWER_COLOR` in `game/models.py`, mirrored as constants in field mode.
- [x] 1.4 `Tower.resolved_icon` / `resolved_color`: tower override → type → default, per facet.
- [x] 1.5 Tests: per-facet override; clearing an override reverts to the type; deleting a type leaves its towers resolvable on the defaults.

## 2. Radius resolution — all three sites

- [x] 2.1 `effective_proximity()` gains the type layer: tower → type → game.
- [x] 2.2 `game/views.py` nearby filter coalesces through the joined type. Done by *extracting* `proximity_radius_expression()` into `game/models.py` beside the Python helper, so the two fallbacks are one definition read together rather than two that must be remembered.
- [x] 2.3 Confirm `game/presence.py` follows via the helper and needs no edit of its own. Confirmed: it calls the helper, so it inherited the type layer with no edit.
- [x] 2.4 Test that the Python helper and the SQL annotation agree for the same tower — asserted against each other, not against an expected number, so it survives a change of default. `test_python_and_sql_radius_agree`. Confirmed non-vacuous: dropping the type layer from the SQL expression fails it with "SQL and Python disagree for radius-type-only".
- [x] 2.5 Test that a type's radius takes effect for a tower that sets none, and that the tower's own value still wins.

## 3. API

- [x] 3.1 `/api/staff/tower-types/` CRUD, staff-only.
- [x] 3.2 `AdminTowerSerializer`: writable `tower_type`, `icon`, `color`; read-only resolved `icon`/`color` under distinct names so "set" and "resolved" are both legible. `tower_type`, `icon`, `color` writable; `resolved_icon`, `resolved_color`, `tower_type_name` read-only.
- [x] 3.3 Deleting a type in use returns its towers to the defaults rather than failing or cascading. `on_delete=SET_NULL`.
- [x] 3.4 Tests for each, including that the resolved fields are present on a tower with no type.

## 4. Staff UI

- [x] 4.1 `/tower-types` manager: list, create, edit, delete; each row rendered as it will appear on a map.
- [x] 4.2 Icon picker searching the bundled Bootstrap Icons set, storing the class name. 24 suggested icons, filterable, with the raw class name editable for anything outside the set.
- [x] 4.3 Nav entry under Build; nav-coverage assertion updated.
- [x] 4.4 Tower editing offers type selection plus per-facet "reset to type" for icon and colour. Towers page gains a Type column with a resolved-style swatch, plus "reset styling to type" when a row overrides. The radius placeholder now names what it inherits ("30 (type)" / "game default") instead of saying "inherit".

## 5. Field mode

- [x] 5.1 Type chip row in the capture panel — one tap applies icon, colour and radius.
- [x] 5.2 Show the radius the chosen type implies, and warn when it is smaller than the current GPS accuracy.
- [x] 5.3 Saving with no type stays possible and unchanged.
- [x] 5.4 Field map paints placed towers by resolved style. The placed pin repaints on selection.

## 6. Verification

- [x] 6.1 `ruff check .` clean.
- [ ] 6.2 Backend suite and coverage gate clean.
- [x] 6.3 Frontend suite clean; both apps build.
- [x] 6.4 Browser: create a type, drop a tower with it in field mode, confirm it paints and carries the radius. Dropped "E2E Typed Oak" as a Landmark tree: saved with the type, radius resolved to 30 (not the game default 50), styling `bi-tree-fill`/#1E8449, accuracy provenance 6.0 m, staged inactive.
- [x] 6.5 Browser: override one facet, confirm the other still follows the type. Verified in the browser: selecting a type repaints the pin and states its radius; a 25 m type under a ±40 m fix warns that players may not be able to reach it, and the warning clears on deselect.
