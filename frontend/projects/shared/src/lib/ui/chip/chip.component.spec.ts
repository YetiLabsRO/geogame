import { ComponentFixture, TestBed } from '@angular/core/testing';

import { UiChipComponent } from './chip.component';

describe('UiChipComponent', () => {
  let fixture: ComponentFixture<UiChipComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [UiChipComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(UiChipComponent);
  });

  it('defaults to the neutral tone', () => {
    fixture.detectChanges();

    expect((fixture.nativeElement as HTMLElement).getAttribute('data-tone')).toBe('neutral');
    expect((fixture.nativeElement as HTMLElement).hasAttribute('data-team')).toBe(false);
  });

  it('applies --team-color and switches to the team style when teamColor is set', () => {
    fixture.componentRef.setInput('tone', 'brand');
    fixture.componentRef.setInput('teamColor', '#446279');
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    expect(host.style.getPropertyValue('--team-color')).toBe('#446279');
    expect(host.getAttribute('data-team')).toBe('');
  });
});
