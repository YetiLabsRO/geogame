import { ChangeDetectionStrategy, Component, inject } from '@angular/core';

import { AuthService } from 'shared';

@Component({
  selector: 'app-home',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="row justify-content-center">
      <div class="col-md-8 col-lg-6">
        <h1 class="h3 mb-3">
          @if (profile(); as p) {
            Welcome, {{ p.first_name || p.username }}
          } @else {
            Welcome
          }
        </h1>
        <div class="alert alert-info">
          The map is coming soon. This is a placeholder while the player map view is built.
        </div>
      </div>
    </div>
  `,
})
export class HomeComponent {
  private readonly auth = inject(AuthService);
  protected readonly profile = this.auth.profile;
}
