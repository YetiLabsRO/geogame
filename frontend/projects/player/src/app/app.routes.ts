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
  { path: '**', redirectTo: '' },
];
