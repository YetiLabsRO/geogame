import { Component, computed, inject } from '@angular/core';
import { Router, RouterLink, RouterOutlet } from '@angular/router';

import { AuthService } from 'shared';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  protected readonly isAuthenticated = this.auth.isAuthenticated;
  protected readonly username = computed(() => this.auth.profile()?.username ?? null);

  constructor() {
    if (this.auth.isAuthenticated() && this.auth.profile() === null) {
      this.auth.fetchProfile().subscribe({ error: () => {} });
    }
  }

  protected logout(): void {
    this.auth.logout().subscribe({
      next: () => this.router.navigateByUrl('/login'),
      error: () => this.router.navigateByUrl('/login'),
    });
  }
}
