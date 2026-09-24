## ADDED Requirements

### Requirement: Replay frames are the common model

The system SHALL represent a replay as an ordered series of frames, each a complete reconstructed snapshot of the game world at one point in the run, regardless of whether the run was simulated or recorded.

#### Scenario: Frame contents

- **WHEN** a replay frame is produced from either source
- **THEN** it SHALL carry a monotonic frame index, a human-readable label, player positions with team identity and role where applicable, tower ownership, and derived team standings
- **AND** a frame SHALL be a full snapshot rather than a delta, so seeking to any index requires no replay of preceding frames

#### Scenario: Simulated source

- **WHEN** frames are built from a `SimulationRun`'s event tape
- **THEN** the frame index SHALL be the simulation tick
- **AND** the frame SHALL carry no wall-clock instant, because a simulated run has no real clock

#### Scenario: Recorded source

- **WHEN** frames are built from a recorded Session
- **THEN** the frame index SHALL be the ordinal of a fixed-width time bucket
- **AND** each frame SHALL carry the wall-clock instant that bucket represents

### Requirement: Staff replay bundle API

The system SHALL expose a staff-only endpoint returning everything needed to replay a recorded Session, in one response, so that scrubbing requires no further requests.

#### Scenario: Fetching a replay bundle

- **WHEN** a staff user calls `GET /api/staff/sessions/{id}/replay/`
- **THEN** the system SHALL return the Session's identity and window, the team roster with colors, the participating players, tower identity and geometry, zone geometry, tower ownership intervals, and per-frame downsampled player positions
- **AND** the response SHALL state the frame interval used and the number of frames

#### Scenario: Non-staff access

- **WHEN** a non-staff user calls the replay endpoint
- **THEN** the system SHALL deny the request
- **AND** no replay surface SHALL be exposed in the player app

#### Scenario: Requesting a frame interval

- **WHEN** the caller passes `interval_seconds`
- **THEN** the system SHALL use it as the frame width, subject to a server-enforced minimum
- **AND** when the resulting frame count would exceed the server cap, the system SHALL coarsen the interval to fit and report the interval it actually used rather than truncating the session

#### Scenario: Windowing a replay

- **WHEN** the caller passes a `from` and/or `to` instant
- **THEN** the system SHALL restrict frames to that window
- **AND** ownership intervals overlapping the window SHALL be included so the first frame shows correct tower ownership rather than an empty map

### Requirement: Bounded bundle size

The system SHALL return at most one position per player per frame, so that bundle size scales with roster and frame count rather than with ping volume.

#### Scenario: Downsampling a dense series

- **WHEN** a player produced many pings within one frame interval
- **THEN** the bundle SHALL include only that player's most recent ping in that interval
- **AND** the discarded pings SHALL remain available through the existing location-history endpoint for raw inspection

### Requirement: Position carry-forward with a staleness horizon

The system SHALL carry a player's last known position forward across frames in which they produced no sample, and SHALL stop drawing them once that position is too old to be credible.

#### Scenario: A brief gap

- **WHEN** a player produced no sample for a frame but produced one within the staleness horizon
- **THEN** the replay SHALL show them at their last known position

#### Scenario: A long gap

- **WHEN** a player's last known position is older than the staleness horizon
- **THEN** the replay SHALL omit that player from the frame rather than showing them stationary
- **AND** the player SHALL reappear at their next recorded sample

#### Scenario: A player with no position yet

- **WHEN** a frame precedes a player's first recorded sample
- **THEN** the replay SHALL omit that player from the frame

### Requirement: Ownership is resolved from recorded intervals

The system SHALL derive tower ownership in a recorded replay from stored ownership intervals rather than reconstructing it from a capture event log.

#### Scenario: Ownership at a frame

- **WHEN** a frame at instant `t` is built for a recorded Session
- **THEN** a tower SHALL be shown as owned by the team whose ownership interval started at or before `t` and has not ended by `t`
- **AND** a tower with no such interval SHALL be shown as unclaimed

#### Scenario: Ownership changes hands mid-replay

- **WHEN** a tower was captured by another team during the session
- **THEN** frames before the capture SHALL show the previous owner and frames at or after it SHALL show the new owner

### Requirement: Honest degradation when data is absent

The system SHALL replay whatever was recorded and SHALL state plainly which layers are unavailable and why, rather than failing or rendering a silently empty map.

#### Scenario: A session that never tracked location

- **WHEN** a staff user replays a Session whose effective `location_tracking_enabled` was false
- **THEN** the system SHALL still return and render tower ownership and standings over time
- **AND** the view SHALL state that player tracks are unavailable because location tracking was disabled for that Session

#### Scenario: Players who did not consent

- **WHEN** some players never consented or withdrew consent
- **THEN** the replay SHALL include only consenting players' tracks
- **AND** the view SHALL report how many of the roster are plotted

#### Scenario: A window reaching past the retention cutoff

- **WHEN** a Session's replay window begins before its retention cutoff, so part of its history has been or is about to be purged
- **THEN** the bundle SHALL report the retention window, the retention cutoff, and the earliest surviving sample
- **AND** the timeline SHALL mark the purged span rather than presenting what survives as the whole session

#### Scenario: A late first sample is not a purge

- **WHEN** a Session's earliest surviving sample is later than the window start simply because nobody pinged at the instant the Session opened
- **THEN** the system SHALL NOT report the history as purged
- **AND** the timeline SHALL mark no purged span

### Requirement: Implausible samples are excluded

The system SHALL exclude location samples whose client-reported time falls outside the Session's window by more than a grace period.

#### Scenario: A skewed client clock

- **WHEN** a ping carries a `recorded_at` well outside the Session's start and end
- **THEN** the system SHALL exclude it from replay frames
- **AND** the bundle SHALL still expose server `received_at` alongside included samples so a suspect track can be diagnosed

### Requirement: Frame assignment is exact

The system SHALL assign a sample to the frame containing its recorded time, independently of sub-second offsets in the replay window's start.

#### Scenario: A window start carrying microseconds

- **WHEN** a Session's window starts part-way through a second and a sample falls just inside the last whole second of a frame
- **THEN** the system SHALL place that sample in that frame, not the next one
- **AND** the assignment SHALL NOT vary with the wall clock

### Requirement: Time-window bounds are validated, not silently ignored

The system SHALL reject an unparseable `from` or `to` bound on the staff replay and location-history reads, rather than quietly returning the whole series.

#### Scenario: An unparseable bound

- **WHEN** a staff user passes a `from` or `to` value that is not an ISO datetime — most often a `+00:00` offset left unencoded, which arrives as a space
- **THEN** the system SHALL reject the request and name the bound it could not parse
- **AND** it SHALL NOT return the unfiltered series as though the window had been applied

### Requirement: Staff replay view

The system SHALL provide a staff view that plays a recorded Session back on a map with a timeline scrubber.

#### Scenario: Replaying a session

- **WHEN** a staff user opens a Session's replay
- **THEN** the view SHALL render zones, towers colored by owner at the current frame, and player positions colored by team, on a map
- **AND** it SHALL provide play, pause, step, and seek controls over the frame timeline
- **AND** the current frame's wall-clock instant SHALL be displayed

#### Scenario: Scrubbing does not call the backend

- **WHEN** a staff user drags the timeline
- **THEN** the view SHALL reconstruct frames from the already-fetched bundle without issuing further requests

#### Scenario: Filtering a replay

- **WHEN** a staff user filters by team
- **THEN** the map SHALL plot only that team's players
- **AND** the standings panel SHALL remain complete, so the filtered team can be read in context

#### Scenario: Inspecting raw pings

- **WHEN** a staff user needs exact sample values
- **THEN** the view SHALL offer the raw ping feed for the session, filterable by user, team, and time window

### Requirement: Standings shown during replay are derived, not scores

The system SHALL present per-frame team standings derived from tower ownership at that frame, and SHALL NOT present them as the team's score.

#### Scenario: Reading standings mid-replay

- **WHEN** a staff user reads the standings panel at any frame
- **THEN** it SHALL show towers held per team at that frame
- **AND** it SHALL indicate that true score accrues over time from zone control and is not reconstructed here
