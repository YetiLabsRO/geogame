import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';

import { UiBottomNavComponent, UiNavItem } from './bottom-nav.component';

/** design-system task 3.6 — active item for /team/12 with route: '/team'. */
describe('UiBottomNavComponent', () => {
  let fixture: ComponentFixture<UiBottomNavComponent>;
  let router: Router;

  const items: UiNavItem[] = [
    { label: 'Journey', icon: 'map', route: '/', exact: true },
    { label: 'Society', icon: 'users', route: '/team' },
  ];

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [UiBottomNavComponent],
      // A wildcard route lets navigateByUrl resolve for any test URL below —
      // UiBottomNavComponent never renders a <router-outlet>, so what (if
      // anything) it "activates" is irrelevant here.
      providers: [provideRouter([{ path: '**', children: [] }])],
    }).compileComponents();

    router = TestBed.inject(Router);
    fixture = TestBed.createComponent(UiBottomNavComponent);
    fixture.componentRef.setInput('items', items);
  });

  function activeLabels(): string[] {
    const anchors = Array.from(
      fixture.nativeElement.querySelectorAll('a.ui-bottom-nav__item--active'),
    ) as HTMLAnchorElement[];
    return anchors.map((a) => a.textContent?.trim() ?? '');
  }

  it('marks the Society tab active for a nested route like /team/12', async () => {
    await router.navigateByUrl('/team/12');
    fixture.detectChanges();

    const active = activeLabels();
    expect(active.some((label) => label.includes('Society'))).toBe(true);
    expect(active.some((label) => label.includes('Journey'))).toBe(false);
  });

  it('only marks the root item active at the exact root path', async () => {
    await router.navigateByUrl('/');
    fixture.detectChanges();

    const active = activeLabels();
    expect(active.some((label) => label.includes('Journey'))).toBe(true);
    expect(active.some((label) => label.includes('Society'))).toBe(false);
  });

  it('does not treat /teams as a match for the /team tab', async () => {
    await router.navigateByUrl('/teams');
    fixture.detectChanges();

    expect(activeLabels().some((label) => label.includes('Society'))).toBe(false);
  });
});
