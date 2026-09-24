## MODIFIED Requirements

### Requirement: Attach reference photos to a tower in the field

The system SHALL let a curator capture and attach reference media — photos, audio notes and short video — to a Tower or a Zone while on site.

#### Scenario: Photographing the objective

- **WHEN** a curator captures a photo for a Tower or Zone being authored
- **THEN** the system SHALL store it as reference media linked to that subject, recording its kind, who captured it and when
- **AND** it SHALL serve as a reference that helps players recognise the physical objective, distinct from player challenge submissions
- **AND** a Tower or Zone MAY have many reference media

#### Scenario: Recording a spoken note

- **WHEN** a curator records an audio note for the subject in hand
- **THEN** the system SHALL store it as reference media of the audio kind
- **AND** field mode SHALL show that recording is in progress and how long it has run

#### Scenario: Recording a short clip

- **WHEN** a curator records a video clip for the subject in hand
- **THEN** the system SHALL store it as reference media of the video kind, within the documented duration limit

#### Scenario: Reviewing what was captured

- **WHEN** a curator has attached media to the subject in hand
- **THEN** field mode SHALL show what is attached
- **AND** it SHALL allow removing an attachment made by mistake before moving on

### Requirement: Offline-tolerant capture and sync

The system SHALL let a curator capture field-authoring edits without connectivity and sync them when the device is back online.

#### Scenario: Capturing offline

- **WHEN** a curator drops towers, captures media, or draws zones while the device has no network connection
- **THEN** the system SHALL queue those edits locally on the device so they survive reload
- **AND** it SHALL indicate that the edits are pending sync

#### Scenario: Queuing media

- **WHEN** queued media is held on the device
- **THEN** it SHALL be stored in a way able to carry files of the sizes the supported kinds allow
- **AND** queuing a capture the system would accept SHALL NOT fail for want of storage quota

#### Scenario: Syncing on reconnect

- **WHEN** network connectivity is restored
- **THEN** the system SHALL upload the queued Towers, Zones, media, and challenge associations to the server
- **AND** media queued against a Tower that had not yet reached the server SHALL follow that Tower to its assigned identity
- **AND** no item SHALL leave the queue until the server confirms it
- **AND** it SHALL surface any items that failed to sync so the curator can retry or discard them
