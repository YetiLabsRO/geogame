import { ComponentFixture, TestBed } from '@angular/core/testing';

import { QrCodeComponent } from './qr-code.component';

describe('QrCodeComponent', () => {
  let fixture: ComponentFixture<QrCodeComponent>;
  let component: QrCodeComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [QrCodeComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(QrCodeComponent);
    component = fixture.componentInstance;
    fixture.componentRef.setInput('value', 'https://example.com/invite/abc123');
  });

  it('creates', () => {
    expect(component).toBeTruthy();
  });

  it('renders an inline <svg> once the value is set', () => {
    fixture.detectChanges();

    const host = fixture.nativeElement.querySelector('.qr-canvas') as HTMLElement | null;
    expect(host).toBeTruthy();
    expect(host?.getAttribute('role')).toBe('img');
    expect(host?.querySelector('svg')).toBeTruthy();
    expect(host?.querySelectorAll('rect').length).toBeGreaterThan(1);
    expect(host?.getAttribute('aria-label')).toBe('https://example.com/invite/abc123');
  });

  it('honours the size input via inline width/height', () => {
    fixture.componentRef.setInput('size', 128);
    fixture.detectChanges();

    const host = fixture.nativeElement.querySelector('.qr-canvas') as HTMLElement;
    expect(host.style.width).toBe('128px');
    expect(host.style.height).toBe('128px');
  });

  it('prefers ariaLabel over the raw value', () => {
    fixture.componentRef.setInput('ariaLabel', 'Scan to join team');
    fixture.detectChanges();

    const host = fixture.nativeElement.querySelector('.qr-canvas') as HTMLElement;
    expect(host.getAttribute('aria-label')).toBe('Scan to join team');
  });

  it('renders nothing for an empty value', () => {
    fixture.componentRef.setInput('value', '');
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('.qr-canvas')).toBeNull();
  });
});
