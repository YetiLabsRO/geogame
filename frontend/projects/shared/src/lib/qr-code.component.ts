import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { inject } from '@angular/core';
import QRCode, { QRCodeErrorCorrectionLevel } from 'qrcode';

@Component({
  selector: 'lib-qr-code',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (svg(); as markup) {
      <div
        class="qr-canvas"
        role="img"
        [attr.aria-label]="ariaLabel() ?? value()"
        [style.width.px]="size()"
        [style.height.px]="size()"
        [innerHTML]="markup"
      ></div>
    }
  `,
  styles: `
    :host {
      display: inline-block;
      line-height: 0;
    }
    .qr-canvas ::ng-deep svg {
      display: block;
      width: 100%;
      height: 100%;
    }
  `,
})
export class QrCodeComponent {
  readonly value = input.required<string>();
  readonly size = input<number>(256);
  readonly errorCorrectionLevel = input<QRCodeErrorCorrectionLevel>('M');
  readonly ariaLabel = input<string | undefined>(undefined);

  private readonly sanitizer = inject(DomSanitizer);

  readonly svg = computed<SafeHtml | null>(() => {
    const value = this.value();
    if (!value) {
      return null;
    }
    const qr = QRCode.create(value, { errorCorrectionLevel: this.errorCorrectionLevel() });
    return this.sanitizer.bypassSecurityTrustHtml(renderSvg(qr));
  });
}

interface QrMatrix {
  modules: { size: number; data: ArrayLike<number> };
}

function renderSvg(qr: QrMatrix): string {
  const size = qr.modules.size;
  const data = qr.modules.data;
  const margin = 1;
  const viewSize = size + margin * 2;
  const rects: string[] = [];
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      if (data[y * size + x]) {
        rects.push(`<rect x="${x + margin}" y="${y + margin}" width="1" height="1"/>`);
      }
    }
  }
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${viewSize} ${viewSize}" ` +
    `shape-rendering="crispEdges" fill="#000">` +
    `<rect width="${viewSize}" height="${viewSize}" fill="#fff"/>` +
    rects.join('') +
    `</svg>`
  );
}
