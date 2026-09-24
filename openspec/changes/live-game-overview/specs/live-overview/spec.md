## ADDED Requirements

### Requirement: Live overview of a running Session

The system SHALL provide a map-dominant, read-only view of one Session as it runs, showing where the game currently stands.

#### Scenario: Opening the overview

- **WHEN** a staff user opens a Session's live overview
- **THEN** the system SHALL render a map of that Session's towers and zones
- **AND** each tower SHALL be painted with its current owning team's colour, or a neutral colour when unowned
- **AND** each zone SHALL be tinted by the team currently controlling it, or left neutral when no single team controls it
- **AND** the view SHALL show current standings per team alongside the map
- **AND** the view SHALL state the Session's current lifecycle state, including when it is paused or finished

#### Scenario: A Game with several TeamGroups

- **WHEN** a Game's TeamGroups play the same map at once, so a tower has one owner per group
- **THEN** the overview SHALL paint one group at a time rather than overlaying them
- **AND** it SHALL offer a way to choose which group is shown when there is more than one
- **AND** the standings and the event ticker SHALL be scoped to the group being shown

#### Scenario: A capture while the overview is open

- **WHEN** a tower changes hands while the overview is open
- **THEN** the tower's paint SHALL change to the new owner's colour without the viewer reloading
- **AND** the standings SHALL reflect the resulting score change
- **AND** the capture SHALL appear in a recent-events ticker naming the team and the tower

#### Scenario: Readable across a room

- **WHEN** the overview is displayed in presentation mode
- **THEN** it SHALL omit the staff app's navigation chrome
- **AND** it SHALL remain legible without pointer interaction, requiring no input to keep showing current state

#### Scenario: The overview is read-only

- **WHEN** any viewer interacts with the overview
- **THEN** the system SHALL offer no control that alters game state, roster, scores, or Session lifecycle from that view

### Requirement: Overview snapshot endpoint

The system SHALL expose the overview's contents as a single self-contained snapshot so the view composes one response rather than joining several.

#### Scenario: Staff requests a snapshot

- **WHEN** a staff user calls `GET /api/staff/sessions/{id}/overview/`
- **THEN** the system SHALL return the Session and its lifecycle state, its teams with colours, its tower geometry with each tower's current owner, its zone geometry with each zone's current controller, current standings, any active score multipliers, recent capture events, and player positions subject to the visibility rules below
- **AND** the response SHALL be scoped to that Session alone

#### Scenario: A Session that does not exist

- **WHEN** the requested Session does not exist
- **THEN** the system SHALL return 404

### Requirement: A shared surface applies the Session's live-location configuration

The system SHALL resolve player position visibility on the overview from the Session's effective configuration rather than from the caller's privilege, because the overview's audience is everyone who can see the screen.

#### Scenario: Visibility permits a shared plot

- **WHEN** a Session's effective `location_visibility` is `EVERYONE` and its effective `teammate_visibility_mode` is not `SELECT_COUNT`
- **THEN** the overview SHALL plot the latest position of every consenting player in the Session

#### Scenario: Visibility is caller-relative or suppressed

- **WHEN** a Session's effective `location_visibility` is `NONE` or `OWN_TEAM`, or its effective `teammate_visibility_mode` is `SELECT_COUNT`
- **THEN** the overview SHALL plot no player positions
- **AND** it SHALL state on the page that positions are hidden and why
- **AND** it SHALL continue to show towers, zones, standings, and events

#### Scenario: Staff privilege does not widen a shared surface

- **WHEN** a staff user opens the overview for a Session whose configuration does not permit a shared plot
- **THEN** the system SHALL NOT apply the staff bypass that `GET /api/location/live/` grants
- **AND** no player position SHALL appear in the snapshot

#### Scenario: Consent still governs

- **WHEN** a player has not consented to location tracking for the Session, or has withdrawn consent
- **THEN** that player SHALL NOT appear on the overview under any configuration

### Requirement: Revocable share links

The system SHALL let staff issue a link that shows one Session's overview to a viewer with no account, and SHALL let them revoke it.

#### Scenario: Issuing a link

- **WHEN** a staff user creates a share link for a Session
- **THEN** the system SHALL store a `SessionOverviewLink` bound to that Session with an opaque, unguessable token, the issuing user, and a creation time
- **AND** it SHALL return an address the viewer can open directly
- **AND** the link MAY carry a human-readable label and an optional expiry

#### Scenario: Viewing through a link

- **WHEN** an unauthenticated viewer opens a share link's address
- **THEN** the system SHALL render the overview for the bound Session
- **AND** `GET /api/overview/{token}/` SHALL return a snapshot no broader than the staff snapshot for that Session
- **AND** the view SHALL offer no share-link management and no game controls
- **AND** it SHALL render none of the staff application's navigation or account controls

#### Scenario: A plotted player is not named to a room

- **WHEN** a share-link snapshot includes player positions
- **THEN** it SHALL identify each position by team only
- **AND** it SHALL NOT include the player's username
- **AND** the staff snapshot MAY include the username, which a staff user needs to act on what they see

#### Scenario: Revoking a link

- **WHEN** a staff user revokes a share link
- **THEN** subsequent requests carrying that token SHALL be rejected
- **AND** any realtime connection admitted by that token SHALL stop receiving events

#### Scenario: An expired or unknown token

- **WHEN** a request carries a token that is unknown, inactive, or past its expiry
- **THEN** the system SHALL reject it without disclosing whether the token ever existed

#### Scenario: A share link reaches exactly one Session

- **WHEN** a viewer holds a share link for one Session
- **THEN** it SHALL grant no access to any other Session, to rosters, to submissions, or to session history

#### Scenario: Unauthenticated reads are rate limited

- **WHEN** a share link's endpoints are requested repeatedly
- **THEN** the system SHALL rate limit them per token
- **AND** one token exceeding its limit SHALL NOT affect another token's access

### Requirement: Realtime admission for a share viewer

The system SHALL let a share link receive live events for its Session, restricted to the event types the overview renders.

#### Scenario: Admitting a share viewer

- **WHEN** a client connects to a Session's realtime socket presenting an active share link token for that Session
- **THEN** the system SHALL admit it read-only
- **AND** it SHALL reject the connection when the token is inactive, expired, or bound to a different Session

#### Scenario: Only overview events are forwarded

- **WHEN** an event is broadcast to a Session with an admitted share viewer
- **THEN** the system SHALL forward it only if its type is one of `tower.ownership_changed`, `zone.control_changed`, `scoreboard.updated`, `bonus.appeared`, or `session.state_changed`
- **AND** it SHALL NOT forward `dementor.tick`, which carries per-player detail the overview does not render
- **AND** an event type not on that list SHALL NOT reach a share viewer

#### Scenario: A share token is not a user token

- **WHEN** a connection presents a share link token
- **THEN** the system SHALL NOT resolve it to any user account
- **AND** a connection presenting both a user token and a share token SHALL be rejected rather than granted the union of their access
