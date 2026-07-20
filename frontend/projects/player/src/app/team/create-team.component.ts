import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { CurrentSession, GameApiService, TeamFormationService } from 'shared';

import { extractErrorMessage } from '../auth/form-error';

@Component({
  selector: 'app-create-team',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, RouterLink],
  template: `
    <div class="row justify-content-center">
      <div class="col-lg-6">
        <h1 class="h3 mb-3">Create a team</h1>

        @if (loadError(); as msg) {
          <div class="alert alert-danger">{{ msg }}</div>
        }

        @if (session(); as s) {
          @if (!s.allow_player_team_creation) {
            <div class="alert alert-warning">
              Player team creation is not enabled for this session. Ask the
              organisers to add you to a team.
            </div>
          } @else {
            <div class="card">
              <div class="card-body">
                <form [formGroup]="form" (ngSubmit)="create()" novalidate>
                  <div class="mb-3">
                    <label class="form-label" for="name">Team name</label>
                    <input id="name" type="text" class="form-control" formControlName="name" />
                  </div>
                  @if (s.game.team_groups.length > 0) {
                    <div class="mb-3">
                      <label class="form-label" for="group">Group (optional)</label>
                      <select id="group" class="form-select" formControlName="group">
                        <option [ngValue]="null">No group</option>
                        @for (g of s.game.team_groups; track g.id) {
                          <option [ngValue]="g.id">{{ g.name }}</option>
                        }
                      </select>
                    </div>
                  }

                  @if (submitError(); as msg) {
                    <div class="alert alert-danger py-2">{{ msg }}</div>
                  }

                  <button
                    type="submit"
                    class="btn btn-primary"
                    [disabled]="form.invalid || submitting()"
                  >
                    @if (submitting()) {
                      <span class="spinner-border spinner-border-sm me-1"></span>
                    }
                    Create team
                  </button>
                  <a class="btn btn-link" routerLink="/teams">Browse teams instead</a>
                </form>
              </div>
            </div>
            <p class="form-text mt-2">
              You become the team captain: you can share a join QR, invite
              people and approve join requests.
            </p>
          }
        } @else if (!loadError()) {
          <div class="d-flex align-items-center text-body-secondary">
            <span class="spinner-border spinner-border-sm me-2"></span>
            Loading…
          </div>
        }
      </div>
    </div>
  `,
})
export class CreateTeamComponent {
  private readonly gameApi = inject(GameApiService);
  private readonly teamFormation = inject(TeamFormationService);
  private readonly fb = inject(FormBuilder);
  private readonly router = inject(Router);

  protected readonly session = signal<CurrentSession | null>(null);
  protected readonly loadError = signal<string | null>(null);
  protected readonly submitError = signal<string | null>(null);
  protected readonly submitting = signal(false);

  protected readonly form = this.fb.nonNullable.group({
    name: ['', [Validators.required, Validators.maxLength(255)]],
    group: [null as number | null],
  });

  constructor() {
    this.gameApi.currentSession().subscribe({
      next: (s) => this.session.set(s),
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });
  }

  protected create(): void {
    if (this.form.invalid || this.submitting()) {
      return;
    }
    this.submitting.set(true);
    this.submitError.set(null);
    const { name, group } = this.form.getRawValue();
    this.teamFormation.createTeam({ name, group }).subscribe({
      next: (team) => this.router.navigate(['/team', team.id, 'share']),
      error: (err) => {
        this.submitting.set(false);
        this.submitError.set(extractErrorMessage(err));
      },
    });
  }
}
