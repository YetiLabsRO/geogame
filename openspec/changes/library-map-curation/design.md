# Design — the map-first library

## The diagnosis

The current collections page is not badly laid out. It is the wrong *kind* of interface for the data. Curating a collection means answering questions like "do these belong together", "is this one an outlier", "does this zone actually contain those towers" — every one of which is a spatial question, asked of a screen containing two dropdowns of names and two lists of names. No arrangement of those controls answers any of them.

Field mode has the same fault from the other side: its map is a capture surface with no memory. It draws where you are and what you are making, and nothing you have ever made.

So the fix in both places is the same: draw the library.

## Decision 1 — one map, collections as a selection over it

The alternative was a map per collection: pick a collection, see its members, add from a list. Rejected because the interesting information is precisely what is *not* in the collection yet — the tower two streets over that ought to be, the one four kilometres away that ought not. A map showing only members cannot show you either.

So the library map draws everything, and the selected collection is a highlight over it. Acting on an element toggles its membership. Membership is a property of the relationship, not of the element, so an element can be in several collections at once and the inspector says which — otherwise "remove" reads as "delete", which is the single most dangerous misreading available on this screen.

The existing `add-towers` / `remove-towers` / `add-zones` / `remove-zones` actions already take id lists and already never delete geometry, so this change adds no membership API. What it adds is a way to *see* what you are doing.

## Decision 2 — one feed for the whole repository, and say where that stops working

`GET /api/staff/library/` returns every tower and zone with geometry, resolved styling, media counts and collection membership. One request, because a map that fetches per element is a map that takes a minute to draw and hammers the server while doing it.

This is right for a repository of hundreds and wrong for one of tens of thousands. Rather than pretend otherwise: the endpoint is shaped so a bounding-box or updated-since parameter can be added later without changing what a caller does with the response, and the assumption is written down here so the day it stops holding is a day somebody recognises rather than debugs.

Collection membership rides in the feed as id lists per element, not as a separate request per collection. That inverts the obvious shape — membership is stored on the Collection — but it is what lets the map answer "is this one in?" for every pin without a second lookup, and the number of collections an element belongs to is small.

## Decision 3 — a crosshair, because a draggable marker is the wrong control on a phone

Drag-to-nudge already exists. `placeTowerMarker` creates a `draggable: true` marker and a manual drag already beats the averaged fix. The capability is not missing; the interaction is wrong. It is a roughly 20-pixel target, under the user's own thumb, on a device held at arm's length outdoors, and it is announced in grey fine print below the buttons.

The established mobile pattern is the opposite assignment of roles: the point stays fixed at the centre of the screen and the *map* moves under it. The target becomes the whole map, the thing being positioned is never under the finger doing the positioning, and precision comes from zooming rather than from steadiness.

Two things come with it, and they are what make it trustworthy rather than just easier:

- **A live offset readout.** "12 m from your position" turns an invisible act into a stated one. A curator who has panned the map while walking needs to know the point is no longer where they are standing.
- **A way back.** One control returns the point to the current fix, so an accidental pan is not a reason to start the capture again.

Marker drag stays. It costs nothing, and it is genuinely better with a mouse at a desk.

## Decision 4 — the field map gains memory, and existing elements are openable

Drawing the target collection's members on the field map is the smaller half. The larger half is that a curator standing at an existing tower usually wants to *do something to it* — add the photo they forgot, record a note, fix a position recorded on a bad fix — and today the only way is to go home.

So selecting an existing element opens the same operations capture already offers: attach media, attach a challenge, correct the position. Not a second editing surface, the same one, pointed at an existing row. That keeps one set of behaviours to get right and means the offline queue covers edits for free.

Existing elements are drawn muted, and the element being captured is drawn at full strength, because the one live decision on the screen should be the loudest thing on it.

## Decision 5 — retire the collections page rather than keep two

`/collections` redirects to `/library`. Keeping both would mean two ways to change membership, and the old one is the one that made this change necessary. The redirect is there because links exist — the same reasoning that kept `/sessions/:id/locations` working when the replay view replaced it.

The list did have one virtue worth keeping: it is a good way to scan and search a lot of names quickly. So it survives as the library's side panel, filtered in step with the map, rather than being deleted.

## Non-goals

- **Editing geometry on the library map.** Moving a tower or reshaping a zone stays with the map editor and with field mode. This page curates membership.
- **Bulk membership by rectangle or polygon.** Tempting and probably right eventually. It needs a considered undo story first, because "add these 40 towers" is only pleasant if "no, not those" is one action.
- **Player-facing anything.** The library is a staff surface over the repository; it has no Session scope and no player view.
