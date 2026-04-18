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
    path: 'login',
    loadComponent: () => import('./auth/login.component').then((m) => m.LoginComponent),
  },
  { path: '**', redirectTo: '' },
];
