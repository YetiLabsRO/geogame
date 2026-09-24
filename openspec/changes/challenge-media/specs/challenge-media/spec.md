## ADDED Requirements

### Requirement: Challenge media library

The system SHALL provide a per-Game library of media items — images, audio clips, and video clips — that a creator uploads once and attaches to any number of Challenges in that Game.

#### Scenario: Uploading to the library

- **WHEN** a creator uploads a media file to a Game's library
- **THEN** the system SHALL store it with its `kind` (`IMAGE`, `AUDIO`, or `VIDEO`), an optional `alt_text` describing the file, and the uploading user and timestamp
- **AND** the item SHALL be available to attach to any Challenge of that Game

#### Scenario: One item serves many challenges

- **WHEN** the same library item is attached to several Challenges
- **THEN** the system SHALL store the file once and reference it from each Challenge
- **AND** each attachment SHALL carry its own display order and its own optional caption

#### Scenario: Library is creator-scoped

- **WHEN** a user lists or attaches media for a Game
- **THEN** the system SHALL return and accept only items of Games that user is permitted to author
- **AND** an attempt to attach an item from another creator's Game SHALL be refused

### Requirement: Multipart upload for every media kind

The system SHALL accept media uploads over a multipart endpoint for all three kinds, so audio and video are streamed to storage rather than carried as base64.

#### Scenario: Uploading a video

- **WHEN** a creator uploads a video through the media endpoint
- **THEN** the system SHALL accept it as a multipart file part and stream it to storage
- **AND** SHALL NOT require the file to be base64-encoded

#### Scenario: Existing base64 image paths are unaffected

- **WHEN** a client uploads a tower photo or a submission photo through the existing base64 field
- **THEN** that path SHALL continue to work unchanged

### Requirement: Uploads are validated and rejected, never transcoded

The system SHALL validate each upload against a per-kind MIME allowlist, a per-kind byte ceiling, and a duration ceiling for audio and video, and SHALL reject anything outside them without attempting to convert it.

#### Scenario: A file exceeds its ceiling

- **WHEN** a creator uploads a file larger than its kind's byte ceiling, or longer than its kind's duration ceiling
- **THEN** the system SHALL reject the upload
- **AND** the error SHALL name the limit that was exceeded and the actual value
- **AND** no library item SHALL be created

#### Scenario: A disallowed format

- **WHEN** a creator uploads a file whose type is not in its kind's allowlist
- **THEN** the system SHALL reject the upload and report the accepted types

#### Scenario: Limits are configurable

- **WHEN** an operator changes a size, duration, or MIME allowlist setting
- **THEN** the new limit SHALL apply to subsequent uploads without a code change

### Requirement: Storage backend is swappable

The system SHALL write and read media through Django's storage API, defaulting to local `MEDIA_ROOT`, so that switching to S3-compatible object storage is a configuration change.

#### Scenario: Default deployment needs no new infrastructure

- **WHEN** the system is deployed with default settings
- **THEN** media SHALL be stored under `MEDIA_ROOT` alongside existing tower and submission photos
- **AND** no object-storage credentials or buckets SHALL be required

#### Scenario: Switching to object storage

- **WHEN** an operator configures an S3-compatible storage backend
- **THEN** uploads and delivery SHALL use it with no change to models, views, or serializers

### Requirement: Ordered media on a challenge

The system SHALL let a creator attach one or more media items to a Challenge in an explicit display order, with a per-attachment caption.

#### Scenario: Ordering is explicit and editable

- **WHEN** a creator reorders the media on a Challenge
- **THEN** the system SHALL persist the new order
- **AND** subsequent reads SHALL return the media in that order
- **AND** reordering SHALL NOT require removing or re-uploading any item

#### Scenario: Mixed kinds on one challenge

- **WHEN** a Challenge carries media of more than one kind
- **THEN** the system SHALL preserve the creator's order across kinds rather than grouping by kind

### Requirement: Media delivery inherits challenge visibility

The system SHALL withhold a Challenge's media, including every media URL, whenever it withholds the Challenge itself.

#### Scenario: A hidden challenge leaks no media

- **WHEN** the server withholds a challenge from a team because it is not yet visible to them
- **THEN** the response SHALL contain no media entries and no media URLs for that challenge
- **AND** a client inspecting the response SHALL be unable to infer the challenge's media from it

#### Scenario: Media appears once the challenge does

- **WHEN** the challenge becomes visible to that team
- **THEN** the response SHALL include its media in order, each with its kind, URL, caption, and alt text

### Requirement: Authoring media in the staff app

The staff app SHALL let a creator attach, reorder, caption, describe, and remove a Challenge's media while creating or editing it.

#### Scenario: Attaching media while editing a challenge

- **WHEN** a creator edits a Challenge in the staff app
- **THEN** they SHALL be able to upload a new file or pick an existing item from the Game's library
- **AND** set its caption and alt text, change its position, and remove it from the Challenge

#### Scenario: Upload feedback

- **WHEN** an upload is rejected for size, duration, or format
- **THEN** the staff app SHALL show the reason and the limit alongside the file that failed
- **AND** SHALL keep the rest of the form's state intact

### Requirement: Rendering media in the player app

The player app SHALL render a Challenge's media inline on the challenge card, in the creator's order, alongside its text.

#### Scenario: Rendering each kind

- **WHEN** a player views a challenge that carries media
- **THEN** images SHALL render inline, and audio and video SHALL render with playback controls
- **AND** each item's caption SHALL be shown when set, and its alt text SHALL be available to assistive technology

#### Scenario: Media is fetched on demand

- **WHEN** a challenge card carrying audio or video is rendered
- **THEN** the client SHALL NOT download the media until the player starts playback

#### Scenario: A challenge without media is unchanged

- **WHEN** a player views a challenge that carries no media
- **THEN** the card SHALL render exactly as it did before this capability

### Requirement: Removing library items in use

The system SHALL refuse to delete a library item while any Challenge still uses it, and SHALL report which Challenges those are.

#### Scenario: Deleting an item in use

- **WHEN** a creator deletes a library item that is attached to one or more Challenges
- **THEN** the system SHALL refuse the deletion and name the Challenges using it
- **AND** the item and those Challenges SHALL be left unchanged

#### Scenario: Deleting a challenge detaches rather than deletes

- **WHEN** a Challenge carrying media is deleted
- **THEN** its attachments SHALL be removed and the library items SHALL be retained for reuse
