# Design — tower types and styling

## The field this cannot use

`Tower.category` is `NORMAL` / `RFID`. It reads like a taxonomy field and is not one: it selects the *capture method*, and `NfcTag.clean()` and the RFID landing flow both branch on it. Putting "Fountain" there would break RFID capture. So the taxonomy is a new field, and the collision is worth stating once here so nobody helpfully "tidies" the two together later.

## Decision 1 — types carry defaults, towers override, and the type link survives the disagreement

The alternative was per-tower icon and colour with free-text tags. Rejected for the reason free vocabularies always fail a library: "Fountain", "fountain" and "fântână" become three categories, and nothing carries configuration. The alternative in the other direction — types only, no overrides — fails the first time one fountain sits inside a narrow courtyard and needs a 10 m radius rather than the type's 25 m.

So a tower keeps its type *and* may disagree with it. The override is per facet: a tower that sets its own colour still takes its type's icon. That matters because the common case is "this one is special in exactly one way", and a whole-type-or-nothing override would push curators to abandon the type entirely, which is how a library stops being queryable.

Clearing an override reverts to the type. There is therefore a difference between "no colour" (inherit) and "this colour, which happens to equal the type's" — the field is nullable rather than defaulted, and the UI has to offer "reset to type" rather than only a colour picker.

## Decision 2 — the radius resolution order gets one new step, in all three places at once

`effective_proximity()` is not the only place a tower's capture radius is derived:

| Where | How | What it drives |
| --- | --- | --- |
| `game/models.py` `effective_proximity()` | Python, `tower.proximity_meters or game.proximity_meters` | capture proximity checks |
| `game/views.py` nearby filter | SQL `Coalesce(tower.proximity_meters, game_default)` | which towers appear in "near me" |
| `game/presence.py` | calls the helper | presence geofence fallback |

The third follows the first for free. The second does not, and it is the dangerous one: if the SQL learns the type layer and the Python does not (or vice versa), a tower appears in the player's nearby list under one radius and refuses capture under another. That is a bug that reads as flaky GPS and would take a long evening to find.

So the SQL annotation coalesces through the joined type — `Coalesce(tower.proximity_meters, tower_type.proximity_meters, game_default)` — and a test derives the radius both ways for the same tower and asserts they agree. The test is written against the pair, not against either one's expected value, so it keeps holding if the default changes.

## Decision 3 — the server resolves styling; clients only draw

Icon and colour are served as computed read-only fields alongside the writable overrides. Three clients already draw towers (map editor, field mode, live overview) and a fourth is coming, so "tower ?? type ?? default" implemented four times is four chances to differ — and the way it would differ is subtle, a wrong colour on one screen, not an error anyone reports.

The writable `icon` / `color` overrides stay in the payload too, because the editor needs to know whether a value is set or inherited; the resolved fields answer "what do I paint", the nullable fields answer "what did the curator choose".

## Decision 4 — the type carries styling and radius, and stops there

`discoverability`, `challenge_visibility` and `initial_bonus` all *could* sensibly have per-type defaults, and every one of them would add another resolution chain to keep consistent across a Python path and a query path, as decision 2 shows. The capture radius earns its place because it is physical — it belongs to the kind of object, a fountain being a smaller target than a hilltop. The others are game-design choices that belong to the game, not to the kind of place.

If a later change wants type-level game defaults, the honest shape is a separate "authoring preset" concept applied at collection-to-game assembly time, not more fields on the type.

## Decision 5 — icons are names from the existing icon set, not uploads

The type's icon is a Bootstrap Icons class name, which is what every other icon in the staff app already is. Uploading SVG per type would mean sanitising user SVG (an XSS surface), storing it, and having no sensible fallback for a broken file — a lot of exposure to let someone draw their own fountain. The type manager offers a searchable picker over the set already bundled, and stores the name.

## Non-goals

- **Zone types.** Zones already carry their own `color`, are far fewer, and are drawn as filled shapes where an icon has nowhere to go.
- **Retro-typing the existing library.** Every tower starts untyped and renders exactly as it does today; typing is something a curator does when it helps them.
- **Type-scoped permissions.** Types are repository-wide, like the geometry they describe.
