## Context

`AuthService` keeps two pieces of state: a token, restored from `localStorage` when the service is constructed, and a profile, fetched from `/api/me/` and held only in memory. `isAuthenticated()` derives from the first and is therefore correct immediately on reload; `isStaff()` derives from the second and is `false` until the fetch returns.

`staffGuard` read both synchronously. Route activation happens during bootstrap, long before `/api/me/` resolves, so on every reload the guard saw `authenticated && !isStaff` and produced the redirect meant for genuine non-staff users — `/login?reason=not-staff`.

`authGuard` in the player app reads only the token, so it never had this bug.

## Goals / Non-Goals

**Goals:**

- A reload, a hard refresh, and a deep link all keep a signed-in user signed in and where they are.
- Authorization waits for the state it depends on instead of guessing.
- A token the server rejects ends the session cleanly rather than looping.
- No flash of signed-out chrome while the profile resolves.

**Non-Goals:**

- No change to the token scheme, storage location, or `/api/me/`.
- No refresh tokens, no expiry handling beyond reacting to a 401.
- No route-level profile resolvers or an `APP_INITIALIZER` — see below.
- No change to `authGuard` or the player app.

## Decisions

### The guard resolves the profile; it does not pre-load it globally

`staffGuard` returns an `Observable<boolean | UrlTree>` when the profile is missing, and stays synchronous when it is already loaded.

*Why not `APP_INITIALIZER`:* blocking bootstrap on `/api/me/` would delay the login page and the player app for a request neither needs, and would still need a decision path for the failure case. The guard is where the question is actually asked.

*Why not a route resolver:* it would have to be attached to every guarded route, which is the same omission risk that left `/nfc-tags` unlinked. One guard already sits on all of them.

### `ensureProfile()` shares one in-flight request

The guard and the app shell both want the profile on reload. `ensureProfile()` returns the loaded profile, or a single shared request, so a reload makes one `/api/me/` call rather than two.

*Why it lives on the service:* both callers already inject `AuthService`, and the in-flight request is state about the service's own data. Putting the de-duplication in either caller would leave the other racing it.

### Unknown is not denied — but it is not admitted either

The guard's rule is: decide on a resolved value, whatever that value turns out to be. A non-staff user whose profile arrives late is still redirected; only the *timing* changed, not the policy.

This is the actual bug class, and it is worth naming in the spec rather than just fixing here: an authorization check that reads a not-yet-loaded value as "no" will deny the right people, silently, and only under conditions (reload, cold cache, slow network) that are easy to miss in development.

### A 401 while resolving clears the token

Otherwise a stale token keeps `isAuthenticated()` true forever: the guard would redirect to login, the login page would see a token, and the user could round-trip without ever being told why.

*Trade-off:* only 401 clears the token. A 403 or a network error leaves it alone, because those can mean "this request was not allowed" or "the server is briefly unreachable" rather than "this token is dead", and signing someone out over a flaky connection is its own bug.

### The shell gets an explicit restoring state

While authenticated with the profile still in flight, the staff shell renders a neutral bar rather than falling through to its signed-out branch.

*Why:* the signed-out bar shows a "Sign in" button. Flashing that during a normal reload tells the user they were logged out — the very thing this change is fixing — even though the guard now admits them a moment later.

## Risks / Trade-offs

- **Guarded navigation now awaits a request.** → Only when the profile is absent, which is once per page load; afterwards the guard is synchronous. The app shell was already making this request, so the reload costs no extra round trip.
- **A slow or hanging `/api/me/` delays the first guarded route.** → It resolves to the login redirect on error, so a failure is handled; a slow-but-eventual response shows the restoring bar rather than a blank page. No timeout is imposed, which means a server that never answers leaves the bar up — acceptable for a staff console on a local network, and visible rather than silent.
- **Only 401 clears the token,** so a server that rejects a dead token with 403 would still loop. → DRF's `TokenAuthentication` answers 401 for an invalid token, which is the case that matters here; widening it risks signing users out on ordinary permission errors.
- **The regression is easy to reintroduce** in any future guard that reads a profile-derived signal. → The spec states the rule as a requirement, and `staff.guard.spec.ts` covers the reload case specifically; it was checked against the old implementation to confirm it fails there.
