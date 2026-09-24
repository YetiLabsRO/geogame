## 1. Fix

- [x] 1.1 Add `AuthService.ensureProfile()` — returns the loaded profile or fetches it once, with concurrent callers sharing one in-flight `/api/me/`.
- [x] 1.2 Clear the stored token on a 401 while resolving, so a stale token cannot loop between guard and login.
- [x] 1.3 Make `staffGuard` await the profile when it is not loaded; keep it synchronous when it is.
- [x] 1.4 Preserve the attempted URL on redirect so signing in returns the user there.
- [x] 1.5 Give the staff shell a "restoring session" state so it does not flash its signed-out bar on reload.

## 2. Tests

- [x] 2.1 Cover the guard: unauthenticated, staff with profile loaded, non-staff with profile loaded, staff after a reload, non-staff arriving late, and a rejected token.
- [x] 2.2 Confirm the reload test is not vacuous by running it against the old synchronous guard — it fails there.

## 3. Verification

- [x] 3.1 `ng build staff` and `ng build player` clean.
- [x] 3.2 Frontend test suites clean.
- [x] 3.3 End-to-end in a real browser: sign in, open a deep staff route, hard refresh, confirm the page and sidebar survive and no redirect to `/login` happens.
