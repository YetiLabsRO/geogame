import { ComponentFixture, TestBed } from '@angular/core/testing';

import { UiButtonComponent } from './button.component';

describe('UiButtonComponent', () => {
  let fixture: ComponentFixture<UiButtonComponent>;
  let component: UiButtonComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [UiButtonComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(UiButtonComponent);
    component = fixture.componentInstance;
  });

  it('renders the variant as a host data attribute, defaulting to primary', () => {
    fixture.detectChanges();

    expect((fixture.nativeElement as HTMLElement).getAttribute('data-variant')).toBe('primary');
  });

  it('reflects an explicit variant on the host', () => {
    fixture.componentRef.setInput('variant', 'secondary');
    fixture.detectChanges();

    expect((fixture.nativeElement as HTMLElement).getAttribute('data-variant')).toBe('secondary');
  });

  it('disables the native button while loading and shows the spinner instead of an icon', () => {
    fixture.componentRef.setInput('icon', 'arrow-right');
    fixture.componentRef.setInput('loading', true);
    fixture.detectChanges();

    const button = fixture.nativeElement.querySelector('button') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(fixture.nativeElement.querySelector('.ui-button__spinner')).toBeTruthy();
    expect(fixture.nativeElement.querySelector('ui-icon')).toBeNull();
  });

  it('disables the native button when disabled is set', () => {
    fixture.componentRef.setInput('disabled', true);
    fixture.detectChanges();

    const button = fixture.nativeElement.querySelector('button') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it('emits pressed on click when enabled', () => {
    let pressCount = 0;
    component.pressed.subscribe(() => pressCount++);
    fixture.detectChanges();

    (fixture.nativeElement.querySelector('button') as HTMLButtonElement).click();

    expect(pressCount).toBe(1);
  });
});
