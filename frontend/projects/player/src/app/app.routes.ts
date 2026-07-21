import { Routes } from '@angular/router';

import { authGuard } from 'shared';

export const routes: Routes = [
  {
    path: '',
    pathMatch: 'full',
    canActivate: [authGuard],
    loadComponent: () => import('./map/map.component').then((m) => m.MapComponent),
  },
  {
    path: 'tower/:id',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./tower/tower-detail.component').then((m) => m.TowerDetailComponent),
  },
  {
    path: 'map/:slug',
    canActivate: [authGuard],
    loadComponent: () => import('./map/map.component').then((m) => m.MapComponent),
  },
  {
    path: 'trail',
    canActivate: [authGuard],
    loadComponent: () => import('./trail/trail.component').then((m) => m.TrailComponent),
  },
  {
    path: 'rules',
    loadComponent: () => import('./rules/rules.component').then((m) => m.RulesComponent),
  },
  {
    path: 'team',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./team/my-team.component').then((m) => m.MyTeamComponent),
  },
  {
    path: 'pick-session',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./session-picker/session-picker.component').then(
        (m) => m.SessionPickerComponent,
      ),
  },
  {
    path: 'history',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./history/my-sessions.component').then((m) => m.MySessionsComponent),
  },
  {
    path: 'history/:id',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./history/session-detail.component').then(
        (m) => m.SessionDetailComponent,
      ),
  },
  {
    path: 'login',
    loadComponent: () => import('./auth/login.component').then((m) => m.LoginComponent),
  },
  {
    path: 'register',
    loadComponent: () => import('./auth/register.component').then((m) => m.RegisterComponent),
  },
  {
    path: 'reset',
    loadComponent: () =>
      import('./auth/password-reset-request.component').then(
        (m) => m.PasswordResetRequestComponent,
      ),
  },
  {
    path: 'reset/:uid/:token',
    loadComponent: () =>
      import('./auth/password-reset-confirm.component').then(
        (m) => m.PasswordResetConfirmComponent,
      ),
  },
  {
    path: 'invite/:token',
    loadComponent: () =>
      import('./auth/invite-accept.component').then((m) => m.InviteAcceptComponent),
  },
  {
    path: 'teams',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./team/browse-teams.component').then((m) => m.BrowseTeamsComponent),
  },
  {
    path: 'team/create',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./team/create-team.component').then((m) => m.CreateTeamComponent),
  },
  {
    path: 'team/:id/share',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./team/team-share.component').then((m) => m.TeamShareComponent),
  },
  {
    path: 'team/:id/requests',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./team/join-requests.component').then((m) => m.JoinRequestsComponent),
  },
  {
    path: 'join/:code',
    loadComponent: () =>
      import('./team/join-code.component').then((m) => m.JoinCodeComponent),
  },
  { path: '**', redirectTo: '' },
];
