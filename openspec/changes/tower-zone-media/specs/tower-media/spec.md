## ADDED Requirements

### Requirement: Media attaches to a tower or a zone

The system SHALL let a curator attach reference media to a Tower or to a Zone, recording what it is, who captured it, and when.

#### Scenario: Attaching to a tower

- **WHEN** a curator attaches media to a tower
- **THEN** the system SHALL store the file with its kind, an optional caption, the capturing user and the capture time
- **AND** a tower MAY carry many attachments

#### Scenario: Attaching to a zone

- **WHEN** a curator attaches media to a zone
- **THEN** the system SHALL store it the same way it stores a tower's
- **AND** a zone MAY carry many attachments

#### Scenario: An attachment has exactly one subject

- **WHEN** media is stored
- **THEN** it SHALL reference exactly one of a tower or a zone
- **AND** the system SHALL reject an attachment that references both or neither

#### Scenario: Reference media is not a player submission

- **WHEN** reference media exists for a tower
- **THEN** it SHALL remain distinct from the photos players submit against challenges
- **AND** neither SHALL appear in the other's listings

### Requirement: Media kinds and their bounds

The system SHALL accept photos, audio notes and short video, and SHALL bound each kind.

#### Scenario: Capturing an audio note

- **WHEN** a curator records an audio note on site
- **THEN** the system SHALL store it as media of the audio kind
- **AND** it SHALL record the clip's duration

#### Scenario: Capturing a video clip

- **WHEN** a curator records a video clip
- **THEN** the system SHALL store it as media of the video kind, subject to a documented maximum duration
- **AND** a clip exceeding that duration SHALL be rejected with a message saying the limit

#### Scenario: An oversized upload

- **WHEN** an upload exceeds the size limit for its kind
- **THEN** the system SHALL reject it and say which limit it exceeded
- **AND** the rejection SHALL NOT consume the curator's queued capture, which stays available to retry or discard

#### Scenario: An unsupported file

- **WHEN** an upload's type does not match any supported kind
- **THEN** the system SHALL reject it rather than storing an attachment nothing can play or display

### Requirement: Media outlives curation changes

The system SHALL keep media attached to its subject through changes that do not delete the subject.

#### Scenario: Recollecting the geometry

- **WHEN** a tower or zone is removed from a Collection, or added to another
- **THEN** its media SHALL be unaffected

#### Scenario: Deleting the subject

- **WHEN** a tower or zone is deleted
- **THEN** its media SHALL be deleted with it, having nothing left to describe

### Requirement: Existing reference photos are carried over

The system SHALL preserve every previously captured tower reference photo when reference media becomes general.

#### Scenario: Migrating

- **WHEN** the system moves to the general media model
- **THEN** every existing tower reference photo SHALL become media of the image kind
- **AND** it SHALL keep its stored file, caption, capturing user and capture time
- **AND** no stored file SHALL be moved, re-encoded or re-uploaded
