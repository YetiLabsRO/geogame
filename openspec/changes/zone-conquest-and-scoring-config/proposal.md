## Why

Three scoring rules are hardcoded today, which blocks running differently-tuned events on the same map. Zone control is fixed to strict majority of towers; capture proximity is a single game-wide radius that cannot vary per tower (a landmark tower and a wide plaza tower want different radii); and the zone score functions accrue in hardcoded minutes, so short "sprint" events or day-long campaigns cannot re-cadence scoring without rewriting formulas. This change turns each of these into a configuration knob with behavior-preserving defaults, following the established per-Game-default / per-Session-or-per-object-override pattern (see `game-configuration` and the pause/failure knobs).

## What Changes

- Make **zone conquest** a configurable rule via a `conquest_rule` enum: `ALL` (a team must hold every active tower in the zone), `MAJORITY` (strict majority — current behavior, the default), or `ANY` (holding at least one active tower). Configurable per `Zone` (per-object override) over a per-`Game` default with an optional per-`Session` override.
- Add a **per-tower `proximity_meters` override** on `Tower`, falling back to the Game's existing game-wide `proximity_meters` default when unset. Nothing changes for existing towers (all resolve to the game-wide radius).
- Make the **scoring time-unit** configurable via a `score_time_unit` enum: `SECOND`, `MINUTE` (default), or `HOUR`. The zone score functions accrue per configured unit instead of hardcoded minutes; with the `MINUTE` default the historical `mins` value is unchanged so existing formulas produce identical scores. Configurable as a per-`Game` default with an optional per-`Session` override.
- Generalize the `scoring` capability: the hardcoded majority-rule requirement is replaced by the configurable conquest-rule requirements (with strict majority retained as the default), and the zone score functions read the effective time unit.
- Expose all three knobs (Game defaults, Session overrides, Zone/Tower per-object overrides) over the staff REST API and staff editors.

## Capabilities

### New Capabilities
<!-- None -->

### Modified Capabilities
- `scoring`: zone control becomes a configurable conquest rule (`ALL`/`MAJORITY`/`ANY`, default `MAJORITY`); the zone score functions accrue per a configurable time unit (`SECOND`/`MINUTE`/`HOUR`, default `MINUTE`).
- `geographic-map`: `Zone` gains an optional `conquest_rule` override; `Tower` gains an optional `proximity_meters` override with the game-wide default as fallback.
- `game-configuration`: `Game` gains `zone_conquest_rule` (default `MAJORITY`) and `score_time_unit` (default `MINUTE`) rule knobs, each overridable per `Session`.

## Impact

- **Models**: add `Game.zone_conquest_rule` (default `MAJORITY`) and `Game.score_time_unit` (default `MINUTE`); add nullable `Session.zone_conquest_rule` and `Session.score_time_unit` overrides; add nullable `Zone.conquest_rule` override; add nullable `Tower.proximity_meters` override. All additive with behavior-preserving defaults (no data migration).
- **APIs**: serializers for Games, Sessions, Zones, and Towers expose the new fields; the `/api/zones/` and `/api/towers/` payloads keep working, with proximity filtering honoring the per-tower radius.
- **Scoring engine**: zone-control recomputation dispatches on the effective conquest rule; the zone score function converts the ownership window duration into the effective time unit before applying the formula.
- **Frontend**: staff Game/Session rule editor gains conquest-rule and time-unit selectors; the Zone editor gains a conquest-rule override; the Tower editor gains a proximity override.
- **Migrations/other**: one additive schema migration; no data backfill required because defaults reproduce current behavior.
