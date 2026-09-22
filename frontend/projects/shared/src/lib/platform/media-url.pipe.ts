import { Pipe, PipeTransform, inject } from '@angular/core';

import { PlatformService } from './platform.service';

/** Template helper for `PlatformService.mediaUrl()` — `{{ tower.photo | mediaUrl }}`. */
@Pipe({ name: 'mediaUrl', standalone: true, pure: true })
export class MediaUrlPipe implements PipeTransform {
  private readonly platform = inject(PlatformService);

  transform(path: string | null | undefined): string {
    return this.platform.mediaUrl(path);
  }
}
