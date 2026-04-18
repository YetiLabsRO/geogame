import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';

@Component({
  selector: 'app-rules',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  template: `
    <div class="row justify-content-center">
      <div class="col-lg-8">
        <a routerLink="/" class="small text-body-secondary">&larr; Back to map</a>
        <h1 class="h2 mt-2 mb-3">Reguli Cercetador</h1>

        <p class="lead">
          În Cetate o să găsiți mai multe puncte cheie, care controlează zona din jurul lor.
          Fiecare punct poate fi controlat de o singură echipă (din fiecare ramură de vârstă)
          într-un moment dat.
        </p>

        <h2 class="h5 mt-4">Cum cucerești o zonă</h2>
        <p>
          Pentru a cuceri o zonă, o echipă trebuie să meargă în apropierea obiectivului care
          controlează zona și să facă provocarea pentru acea zonă. Dacă reușesc, zona devine a
          lor — și cât timp rămâne în posesia lor, adună puncte pentru ei. Cu cât o echipă deține
          o zonă pentru mai mult timp, cu atât îi aduce mai multe puncte.
        </p>
        <ul>
          <li>O echipă poate cuceri oricâte zone.</li>
          <li>Zonele pot fi controlate concomitent de echipe din ramuri de vârstă diferite.</li>
          <li>
            Puteți să vă împărțiți în echipă responsabilitățile oricum doriți, dar nu vă puteți
            împărți în mai mult de 2 grupuri.
          </li>
        </ul>

        <h2 class="h5 mt-4">Zone bonus</h2>
        <p>
          Câtă vreme zonele bonus sunt active, ele pot fi cucerite de orice altă echipă și pot fi
          deținute și ele concomitent de câte o patrulă din fiecare ramură de vârstă diferită.
        </p>

        <h2 class="h5 mt-4">Scorare</h2>
        <p>
          Toate zonele aduc mai multe puncte proporțional cu timpul pentru care le deține o
          echipă. Unele zone colectează puncte accelerat pe măsură ce trece timpul, în timp ce
          altele au un efect invers — dacă le dețineți mult timp, de la un punct încolo nu vor
          mai aduce așa multe puncte. De asemenea, unele puncte cheie aduc un bonus inițial.
        </p>

        <h2 class="h5 mt-4">Pentru a cuceri un obiectiv</h2>
        <p>
          Trebuie să demonstrați că sunteți în apropierea lui (~50m) și să îndepliniți
          provocarea. Apăsați pe turn pe <a routerLink="/">hartă</a> pentru a submite o
          provocare. Liderii confirmă dacă ați făcut sau nu provocarea și vă încredințează
          controlul obiectivului.
        </p>
      </div>
    </div>
  `,
})
export class RulesComponent {}
