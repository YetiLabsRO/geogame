## ADDED Requirements

### Requirement: Media on a challenge

The system SHALL let a Challenge carry one or more media items — images, audio clips, or video clips — as its own content, in an explicit display order.

#### Scenario: Attaching media to a challenge

- **WHEN** a creator adds media to a Challenge
- **THEN** the system SHALL store each item with its `kind` (`IMAGE`, `AUDIO`, or `VIDEO`), its file, an optional caption, optional alt text, an explicit order, and the uploading user and timestamp
- **AND** the media SHALL belong to that Challenge

#### Scenario: A self-contained puzzle

- **WHEN** a creator authors a challenge whose content is the media itself, such as two images to compare
- **THEN** the Challenge SHALL present those items in the creator's order alongside its text
- **AND** the Challenge MAY be bound to a tower without its content referring to that tower

#### Scenario: Ordering is explicit and editable

- **WHEN** a creator reorders the media on a Challenge
- **THEN** the system SHALL persist the new order
- **AND** subsequent reads SHALL return the media in that order
- **AND** reordering SHALL NOT require removing or re-uploading any item

#### Scenario: Mixed kinds on one challenge

- **WHEN** a Challenge carries media of more than one kind
- **THEN** the system SHALL preserve the creator's order across kinds rather than grouping by kind

#### Scenario: Deleting a challenge removes its media

- **WHEN** a Challenge carrying media is deleted
- **THEN** its media items SHALL be deleted with it

### Requirement: Media authoring is creator-scoped

The system SHALL permit media on a Challenge to be added, changed, reordered, or removed only by a user permitted to author that Challenge's Game.

#### Scenario: Out-of-scope media authoring is refused

- **WHEN** a user attempts to add or modify media on a Challenge whose Game they may not author
- **THEN** the system SHALL refuse the operation
- **AND** the Challenge and its media SHALL be left unchanged

### Requirement: Multipart upload for every media kind

The system SHALL accept media uploads over a multipart endpoint for all three kinds, so audio and video are streamed to storage rather than carried as base64.

#### Scenario: Uploading a video

- **WHEN** a creator uploads a video
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
- **AND** no media item SHALL be created

#### Scenario: A disallowed format

- **WHEN** a creator uploads a file whose type is not in its kind's allowlist
- **THEN** the system SHALL reject the upload and report the accepted types

#### Scenario: An unreadable container

- **WHEN** an uploaded audio or video file's duration cannot be determined
- **THEN** the system SHALL reject it rather than storing it with an unknown duration

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
- **THEN** they SHALL be able to upload one or more files, set each item's caption and alt text, change its position, and remove it

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
