## Why

A hard refresh of the staff app signs the user out. The token is stored in `localStorage` and restored when `AuthService` is constructed, so the session itself is intact — but the profile is not restored, and `staffGuard` decides synchronously. In the window before `/api/me/` returns, `isStaff()` reads `false`, the guard reads that as "not staff", and redirects to `/login?reason=not-staff`. A valid staff user is told they are not staff, on every refresh.

The bug is the guard treating *unknown* as *denied*. Nothing in the specs said a session must survive a reload, which is why it went unnoticed.

## What Changes

- `staffGuard` waits for the profile when it has not been loaded yet, instead of deciding on an unresolved value. It stays synchronous when the profile is already in hand.
- Add `AuthService.ensureProfile()`: returns the loaded profile, or fetches it once, with concurrent callers sharing a single in-flight `/api/me/` request so the guard and the app shell do not each fetch on every reload.
- A stored token the server rejects (401) is cleared, so a stale token cannot bounce the user between the guard and the login page forever.
- The staff shell shows a neutral "restoring session" bar while the profile resolves, rather than its signed-out bar, which reads as having been logged out.
- Redirects keep the attempted URL, so signing back in returns the user where they were.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `user-accounts`: adds a requirement that an authenticated session survives a page reload, and that authorization which depends on the profile resolves it rather than treating "not loaded yet" as a denial.

## Impact

- **Modified**: `frontend/projects/shared/src/lib/auth.service.ts` (adds `ensureProfile`), `staff.guard.ts` (async when needed), `frontend/projects/staff/src/app/app.ts` / `app.html` (restoring-session state).
- **No backend change, no API change, no migration.** `/api/me/` and the token scheme are untouched.
- `authGuard` (player app) is unchanged — it only checks the token, which is restored synchronously, so it never had this bug.
- One extra `/api/me/` request per reload, shared between callers — the same request the shell already made, now awaited rather than raced.
