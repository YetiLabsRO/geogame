/*
 * Public API Surface of shared
 */

export * from './lib/shared';
export * from './lib/auth.service';
export * from './lib/auth.guard';
export * from './lib/staff.guard';
export * from './lib/token.interceptor';
export * from './lib/invites.service';
export * from './lib/game-api.service';
export * from './lib/staff-api.service';
export * from './lib/field-queue-store';
export * from './lib/field-sync.service';
export * from './lib/qr-code.component';
export * from './lib/team-formation.service';
export * from './lib/realtime.service';
export * from './lib/dementors.service';
export * from './lib/badges.service';
export * from './lib/platform';

// The `ui-`-prefixed design system (mobile-app). Its barrel covers only
// the token-styled components under lib/ui/<name>/; the flat ones below
// are the older staff primitives and keep their unprefixed names, so
// the two sets export nothing in common.
export * from './lib/ui';

// Theme / shared UI primitives
export * from './lib/ui/info-hint.component';
export * from './lib/ui/field-row.component';
export * from './lib/ui/confirm-dialog.component';
export * from './lib/ui/confirm.service';
export * from './lib/ui/page-header.component';
export * from './lib/ui/stat-tile.component';
export * from './lib/team-colors';
export * from './lib/replay';
