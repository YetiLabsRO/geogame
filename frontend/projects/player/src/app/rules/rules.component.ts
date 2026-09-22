import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';

import { UiCardComponent } from 'shared';

@Component({
  selector: 'app-rules',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, UiCardComponent],
  template: `
    <div class="rules-page">
      <a routerLink="/" class="tr-button-label rules-page__back">&larr; Back to map</a>
      <h1 class="tr-h1 rules-page__title">Rules of the expedition</h1>

      <ui-card class="rules-page__card">
        <p class="tr-body-lg">
          În Cetate o să găsiți mai multe puncte cheie, care controlează zona din jurul lor.
          Fiecare punct poate fi controlat de o singură echipă (din fiecare ramură de vârstă)
          într-un moment dat.
        </p>
      </ui-card>

      <ui-card class="rules-page__card">
        <h2 class="tr-h3 rules-page__heading">Cum cucerești o zonă</h2>
        <p class="tr-body">
          Pentru a cuceri o zonă, o echipă trebuie să meargă în apropierea obiectivului care
          controlează zona și să facă provocarea pentru acea zonă. Dacă reușesc, zona devine a
          lor — și cât timp rămâne în posesia lor, adună puncte pentru ei. Cu cât o echipă deține
          o zonă pentru mai mult timp, cu atât îi aduce mai multe puncte.
        </p>
        <ul class="rules-page__list">
          <li class="tr-body">O echipă poate cuceri oricâte zone.</li>
          <li class="tr-body">Zonele pot fi controlate concomitent de echipe din ramuri de vârstă diferite.</li>
          <li class="tr-body">
            Puteți să vă împărțiți în echipă responsabilitățile oricum doriți, dar nu vă puteți
            împărți în mai mult de 2 grupuri.
          </li>
        </ul>
      </ui-card>

      <ui-card class="rules-page__card">
        <h2 class="tr-h3 rules-page__heading">Zone bonus</h2>
        <p class="tr-body">
          Câtă vreme zonele bonus sunt active, ele pot fi cucerite de orice altă echipă și pot fi
          deținute și ele concomitent de câte o patrulă din fiecare ramură de vârstă diferită.
        </p>
      </ui-card>

      <ui-card class="rules-page__card">
        <h2 class="tr-h3 rules-page__heading">Scorare</h2>
        <p class="tr-body">
          Toate zonele aduc mai multe puncte proporțional cu timpul pentru care le deține o
          echipă. Unele zone colectează puncte accelerat pe măsură ce trece timpul, în timp ce
          altele au un efect invers — dacă le dețineți mult timp, de la un punct încolo nu vor
          mai aduce așa multe puncte. De asemenea, unele puncte cheie aduc un bonus inițial.
        </p>
      </ui-card>

      <ui-card class="rules-page__card">
        <h2 class="tr-h3 rules-page__heading">Pentru a cuceri un obiectiv</h2>
        <p class="tr-body">
          Trebuie să demonstrați că sunteți în apropierea lui (~50m) și să îndepliniți
          provocarea. Apăsați pe turn pe
          <a routerLink="/" class="rules-page__inline-link">hartă</a>
          pentru a submite o provocare. Liderii confirmă dacă ați făcut sau nu provocarea și vă
          încredințează controlul obiectivului.
        </p>
      </ui-card>
    </div>
  `,
  styles: `
    :host {
      display: block;
    }
    .rules-page {
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      gap: var(--spacing-sm);
      padding: var(--spacing-xl) var(--spacing-xl) var(--spacing-2xl);
      max-width: 640px;
      margin: 0 auto;
    }
    .rules-page__back {
      align-self: flex-start;
      color: var(--color-brand-onSurface);
      text-decoration: none;
    }
    .rules-page__title {
      margin-bottom: var(--spacing-xs);
      color: var(--color-text-primary);
    }
    .rules-page__card {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-sm);
    }
    .rules-page__heading {
      color: var(--color-text-primary);
    }
    .rules-page__list {
      margin: 0;
      padding-left: var(--spacing-md);
      display: flex;
      flex-direction: column;
      gap: var(--spacing-2xs);
    }
    .rules-page__inline-link {
      color: var(--color-brand-onSurface);
    }
  `,
})
export class RulesComponent {}
