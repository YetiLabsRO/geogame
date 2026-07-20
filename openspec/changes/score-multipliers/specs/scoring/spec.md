## MODIFIED Requirements

### Requirement: Zone score functions

The system SHALL compute a zone's floating points using the zone's configured `score_type`, then multiply the result by the zone's effective score multiplier factor at the time of evaluation, where `mins` is the duration of the current ownership window in minutes.

#### Scenario: Applying each strategy

- **WHEN** floating points are computed for a held zone
- **THEN** the base value SHALL be:
  - `LINEAR`: `mins`
  - `LOGARITHMIC`: `30 × ln(mins) + mins² / 10000`
  - `EXPONENTIAL` and `BONUS`: `min(mins² / 25 + 50, 200)`
- **AND** the returned floating points SHALL be that base value multiplied by the zone's effective factor (see the `score-multipliers` capability), evaluated at the current time
- **AND** when the ownership window closes and is finalized into locked score, the factor in effect at close time SHALL be used

#### Scenario: No multiplier configured

- **WHEN** no score multiplier applies to a zone
- **THEN** the zone's effective factor SHALL be `1.0`
- **AND** the returned floating points SHALL equal the unmodified base value, preserving existing behaviour

### Requirement: Initial bonus on capture

The system SHALL add a tower's `initial_bonus`, multiplied by the tower's effective score multiplier factor at the moment of capture and floored at 1, to the capturing team's locked score.

#### Scenario: Awarding the bonus

- **WHEN** a tower is assigned to a team via `tower.assign_to_team(team)`
- **THEN** the system SHALL determine `base_bonus` from `tower.initial_bonus` (after any `decrease_initial_bonus` halving)
- **AND** it SHALL add `max(base_bonus × effective_tower_factor, 1)` to that team's locked `score`, where the factor is resolved at capture time (see the `score-multipliers` capability)

#### Scenario: No multiplier configured

- **WHEN** no score multiplier applies to the captured tower
- **THEN** the tower's effective factor SHALL be `1.0`
- **AND** the awarded bonus SHALL equal `max(base_bonus, 1)`, preserving existing behaviour
