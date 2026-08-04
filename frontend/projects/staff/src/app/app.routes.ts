import { Routes } from '@angular/router';

import { staffGuard } from 'shared';

export const routes: Routes = [
  {
    path: '',
    pathMatch: 'full',
    canActivate: [staffGuard],
    loadComponent: () =>
      import('./review/pending-queue.component').then((m) => m.PendingQueueComponent),
  },
  {
    path: 'invites',
    canActivate: [staffGuard],
    loadComponent: () =>
      import('./invites/invites.component').then((m) => m.InvitesComponent),
  },
  {
    path: 'join-requests',
    canActivate: [staffGuard],
    loadComponent: () =>
      import('./join-requests/join-requests.component').then(
        (m) => m.StaffJoinRequestsComponent,
      ),
  },
  {
    path: 'field',
    canActivate: [staffGuard],
    loadComponent: () =>
      import('./field/field-mode.component').then((m) => m.FieldModeComponent),
  },
  {
    path: 'towers',
    canActivate: [staffGuard],
    loadComponent: () =>
      import('./admin/towers.component').then((m) => m.TowersComponent),
  },
  {
    path: 'zones',
    canActivate: [staffGuard],
    loadComponent: () => import('./admin/zones.component').then((m) => m.ZonesComponent),
  },
  // --- map-editor ---
  {
    path: 'map-editor',
    canActivate: [staffGuard],
    loadComponent: () =>
      import('./admin/map-editor/map-editor.component').then(
        (m) => m.MapEditorComponent,
      ),
  },
  // --- end map-editor ---
  {
    path: 'teams',
    canActivate: [staffGuard],
    loadComponent: () => import('./admin/teams.component').then((m) => m.TeamsComponent),
  },
  {
    path: 'challenges',
    canActivate: [staffGuard],
    loadComponent: () =>
      import('./admin/challenges.component').then((m) => m.ChallengesComponent),
  },
  {
    path: 'collections',
    canActivate: [staffGuard],
    loadComponent: () =>
      import('./admin/collections.component').then((m) => m.CollectionsComponent),
  },
  {
    // nfc-native-and-secure-links: tag provisioning + scan audit.
    path: 'nfc-tags',
    canActivate: [staffGuard],
    loadComponent: () =>
      import('./admin/nfc-tags.component').then((m) => m.NfcTagsComponent),
  },
  {
    path: 'games',
    canActivate: [staffGuard],
    loadComponent: () =>
      import('./admin/games.component').then((m) => m.GamesComponent),
  },
  {
    path: 'authoring',
    canActivate: [staffGuard],
    loadComponent: () =>
      import('./admin/authoring-review.component').then((m) => m.AuthoringReviewComponent),
  },
  {
    path: 'sessions',
    canActivate: [staffGuard],
    loadComponent: () =>
      import('./admin/sessions.component').then((m) => m.SessionsComponent),
  },
  {
    path: 'sessions/:id',
    canActivate: [staffGuard],
    loadComponent: () =>
      import('./admin/session-detail.component').then(
        (m) => m.StaffSessionDetailComponent,
      ),
  },
  {
    path: 'sessions/:id/discovery',
    canActivate: [staffGuard],
    loadComponent: () =>
      import('./admin/discovery-matrix.component').then(
        (m) => m.DiscoveryMatrixComponent,
      ),
  },
  {
    path: 'sessions/:id/locations',
    canActivate: [staffGuard],
    loadComponent: () =>
      import('./location/location-history.component').then(
        (m) => m.LocationHistoryComponent,
      ),
  },
  {
    path: 'trails',
    canActivate: [staffGuard],
    loadComponent: () =>
      import('./admin/trail-designer.component').then((m) => m.TrailDesignerComponent),
  },
  {
    path: 'scoreboard',
    canActivate: [staffGuard],
    loadComponent: () =>
      import('./scoreboard/scoreboard.component').then((m) => m.ScoreboardComponent),
  },
  {
    path: 'dementors',
    canActivate: [staffGuard],
    loadComponent: () =>
      import('./dementors/dementors-dashboard.component').then(
        (m) => m.DementorsDashboardComponent,
      ),
  },
  {
    path: 'game-state',
    canActivate: [staffGuard],
    loadComponent: () =>
      import('./game-state/game-state.component').then((m) => m.GameStateComponent),
  },
  {
    path: 'badges',
    canActivate: [staffGuard],
    loadComponent: () =>
      import('./admin/badges.component').then((m) => m.BadgesComponent),
  },
  // --- simulator ---
  {
    path: 'simulator',
    canActivate: [staffGuard],
    loadComponent: () =>
      import('./simulator/simulator.component').then((m) => m.SimulatorComponent),
  },
  {
    path: 'login',
    loadComponent: () => import('./auth/login.component').then((m) => m.LoginComponent),
  },
  // --- game-creation-wizard ---
  {
    path: 'games/new',
    canActivate: [staffGuard],
    loadComponent: () =>
      import('./admin/game-wizard/game-wizard.component').then((m) => m.GameWizardComponent),
  },
  {
    path: 'games/:id/edit',
    canActivate: [staffGuard],
    loadComponent: () =>
      import('./admin/game-wizard/game-wizard.component').then((m) => m.GameWizardComponent),
  },
  // --- end game-creation-wizard ---
  { path: '**', redirectTo: '' },
];
