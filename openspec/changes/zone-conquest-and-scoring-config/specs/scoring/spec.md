## MODIFIED Requirements

### Requirement: Zone score functions

The system SHALL compute a zone's floating points using the zone's configured `score_type`, where `units` is the duration of the current ownership window expressed in the Session's effective scoring time unit (see the `Configurable scoring time unit` requirement).

#### Scenario: Applying each strategy

- **WHEN** floating points are computed for a held zone
- **THEN** the value SHALL be:
  - `LINEAR`: `units`
  - `LOGARITHMIC`: `30 × ln(units) + units² / 10000`
  - `EXPONENTIAL` and `BONUS`: `min(units² / 25 + 50, 200)`
- **AND** `units` SHALL be the ownership-window duration converted into the effective time unit before the formula is applied

#### Scenario: Minute default is unchanged

- **WHEN** the effective scoring time unit is `MINUTE` (the default)
- **THEN** `units` SHALL equal the historical minute-based duration (`mins`)
- **AND** the four formulas SHALL produce identical results to the pre-change behavior, so existing games are unaffected

## ADDED Requirements

### Requirement: Zone conquest rule

The system SHALL grant a zone to the team that satisfies the zone's **effective conquest rule** over that zone's currently-active **member towers** — the active towers linked to the zone through the zone↔tower membership (see the `geographic-map` capability) — computed per TeamGroup, where the rule is one of `ALL`, `MAJORITY`, or `ANY` and defaults to `MAJORITY`. This requirement is the single source of truth for how domination-mode zone control is computed, independent of whether a tower belongs to one zone or several.

#### Scenario: ALL rule

- **WHEN** the effective conquest rule for a zone is `ALL`
- **THEN** the zone SHALL be controlled by a team if and only if that team holds **every** currently-active member tower of the zone
- **AND** if no single team holds all of them, the zone SHALL have no controller

#### Scenario: MAJORITY rule (default)

- **WHEN** the effective conquest rule for a zone is `MAJORITY`
- **THEN** the zone SHALL be controlled by the team holding a **strict majority** of the zone's currently-active member towers
- **AND** if no team holds a strict majority, the zone SHALL have no controller
- **AND** this SHALL be the default rule so migrated games behave exactly as before

#### Scenario: ANY rule with deterministic tie-break

- **WHEN** the effective conquest rule for a zone is `ANY`
- **THEN** a team holding **at least one** currently-active member tower of the zone SHALL be eligible to control it
- **AND** when more than one team in the TeamGroup is eligible, the zone SHALL be awarded to the team holding the most currently-active member towers, ties broken by the most recent tower capture

#### Scenario: Recomputing across a tower's zones on ownership change

- **WHEN** a tower's ownership changes (capture or release)
- **THEN** the system SHALL recompute the controller of **every zone the changed tower belongs to** (its zone membership) per TeamGroup, using each zone's effective conquest rule
- **AND** on a change of controller for a zone, the prior owner's `TeamZoneOwnership` SHALL be closed (its floating score finalized and added to the locked `score`) and a new `TeamZoneOwnership` SHALL be opened for the new controller, if any

#### Scenario: Overlapping zones evaluated independently

- **WHEN** a captured tower belongs to more than one zone (zones that MAY overlap and share towers — see the `geographic-map` capability)
- **THEN** the system SHALL evaluate each of those zones' control independently, using each zone's own effective conquest rule over its own currently-active member towers
- **AND** a team MAY end up controlling one of the zones but not another

### Requirement: Effective zone conquest rule

The system SHALL resolve a zone's effective conquest rule for a Session as the most specific configured value: the `Zone.conquest_rule` override when set, otherwise the `Session.zone_conquest_rule` override when set, otherwise the `Game.zone_conquest_rule` default.

#### Scenario: Per-zone override wins

- **WHEN** a Zone has a non-null `conquest_rule`
- **THEN** that value SHALL be the effective conquest rule regardless of the Session or Game setting

#### Scenario: Session override over game default

- **WHEN** a Zone's `conquest_rule` is unset and the Session has a non-null `zone_conquest_rule`
- **THEN** the Session override SHALL be the effective conquest rule

#### Scenario: Falling back to the game default

- **WHEN** neither the Zone nor the Session sets a conquest rule
- **THEN** the effective conquest rule SHALL be the `Game.zone_conquest_rule` default (`MAJORITY` unless the creator changed it)

### Requirement: Configurable scoring time unit

The system SHALL determine the time unit for zone score accrual from configuration — one of `SECOND`, `MINUTE`, or `HOUR`, defaulting to `MINUTE` — resolved as the `Session.score_time_unit` override when set, otherwise the `Game.score_time_unit` default.

#### Scenario: Resolving the effective time unit

- **WHEN** the system evaluates a zone's floating score for a Session
- **THEN** the effective time unit SHALL be the `Session.score_time_unit` override if set, otherwise the `Game.score_time_unit` default

#### Scenario: Converting the window duration to the unit

- **WHEN** the effective time unit is `SECOND`, `MINUTE`, or `HOUR`
- **THEN** the ownership-window duration SHALL be expressed as `units` in that unit before the `score_type` formula is applied (see the `Zone score functions` requirement)
- **AND** the `MINUTE` default SHALL leave existing scores unchanged

## REMOVED Requirements

### Requirement: Majority-rule zone control

**Reason**: Generalized into the configurable `Zone conquest rule` and `Effective zone conquest rule` requirements above; strict majority is retained as the default rule (`MAJORITY`), so behavior is unchanged for existing games.
