import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import {
  CurrentSession,
  GameApiService,
  TeamFormationService,
  UiAlertComponent,
  UiButtonComponent,
  UiFieldComponent,
  UiInputDirective,
  UiSpinnerComponent,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

@Component({
  selector: 'app-create-team',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    RouterLink,
    UiAlertComponent,
    UiButtonComponent,
    UiFieldComponent,
    UiInputDirective,
    UiSpinnerComponent,
  ],
  template: `
    <div class="team-screen">
      <h1 class="tr-h1">Found a Society</h1>

      @if (loadError(); as msg) {
        <ui-alert tone="danger" [withIcon]="true">{{ msg }}</ui-alert>
      }

      @if (session(); as s) {
        @if (!s.allow_player_team_creation) {
          <ui-alert tone="warning" [withIcon]="true">
            Player team creation is not enabled for this session. Ask the organisers to add you
            to a team.
          </ui-alert>
        } @else {
          <form [formGroup]="form" (ngSubmit)="create()" novalidate class="team-screen__form">
            <ui-field
              label="Team name"
              icon="users"
              [error]="
                form.controls.name.invalid && form.controls.name.touched
                  ? (form.controls.name.hasError('required')
                      ? 'Team name is required.'
                      : 'Team name is too long.')
                  : undefined
              "
            >
              <input uiInput type="text" formControlName="name" placeholder="The Wanderers" />
            </ui-field>

            @if (s.game.team_groups.length > 0) {
              <ui-field label="Group (optional)">
                <select uiInput formControlName="group">
                  <option [ngValue]="null">No group</option>
                  @for (g of s.game.team_groups; track g.id) {
                    <option [ngValue]="g.id">{{ g.name }}</option>
                  }
                </select>
              </ui-field>
            }

            @if (submitError(); as msg) {
              <ui-alert tone="danger" [withIcon]="true">{{ msg }}</ui-alert>
            }

            <ui-button
              type="submit"
              variant="primary"
              [block]="true"
              [loading]="submitting()"
              [disabled]="form.invalid"
            >
              Create
            </ui-button>
            <ui-button variant="secondary" [block]="true" routerLink="/teams">
              Browse societies instead
            </ui-button>
          </form>
          <p class="tr-meta-tiny team-screen__hint">
            You become the team captain: you can share a join QR, invite people and approve join
            requests.
          </p>
        }
      } @else if (!loadError()) {
        <div class="team-screen__loading">
          <ui-spinner />
          <span class="tr-body">Loading…</span>
        </div>
      }
    </div>
  `,
  styles: `
    :host {
      display: block;
    }
    .team-screen {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-lg);
      padding: var(--spacing-sm) var(--spacing-xl) var(--spacing-3xl);
    }
    .team-screen__loading {
      display: flex;
      align-items: center;
      gap: var(--spacing-xs);
      color: var(--color-text-secondary);
      padding-block: var(--spacing-xl);
    }
    .team-screen__form {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-md);
    }
    .team-screen__hint {
      color: var(--color-text-muted);
      text-align: center;
    }
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
