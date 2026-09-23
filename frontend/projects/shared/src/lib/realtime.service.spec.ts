import { provideZonelessChangeDetection } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthService } from './auth.service';
import { RealtimeService } from './realtime.service';

/**
 * What goes on the socket URL (live-overview / realtime-updates).
 *
 * The server refuses a connection presenting both a user token and a
 * share token, so the client must put exactly one there. These tests
 * exist because getting that wrong fails as a refused socket at a venue
 * rather than as anything visible here.
 */

class FakeSocket {
  static opened: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 1;

  constructor(public url: string) {
    FakeSocket.opened.push(url);
  }

  send(): void {}
  close(): void {}
}

function setup(token: string | null) {
  TestBed.configureTestingModule({
    providers: [
      provideZonelessChangeDetection(),
      RealtimeService,
      { provide: AuthService, useValue: { token: () => token } as unknown as AuthService },
    ],
  });
  return TestBed.inject(RealtimeService);
}

describe('RealtimeService socket credentials', () => {
  beforeEach(() => {
    FakeSocket.opened = [];
    vi.stubGlobal('WebSocket', FakeSocket as unknown as typeof WebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    TestBed.resetTestingModule();
  });

  it('sends the user token on the staff path', () => {
    setup('abc123').connect(7);
    expect(FakeSocket.opened).toHaveLength(1);
    expect(FakeSocket.opened[0]).toContain('/ws/session/7/');
    expect(FakeSocket.opened[0]).toContain('token=abc123');
    expect(FakeSocket.opened[0]).not.toContain('overview=');
  });

  it('sends the share token, and only the share token, on the overview path', () => {
    // The account's token must not ride along: presenting both is
    // refused by the server rather than resolved to the stronger.
    setup('abc123').connectShared(7, 'link-token');
    expect(FakeSocket.opened).toHaveLength(1);
    expect(FakeSocket.opened[0]).toContain('overview=link-token');
    expect(FakeSocket.opened[0]).not.toContain('token=abc123');
  });

  it('opens a share socket even with no account signed in', () => {
    setup(null).connectShared(7, 'link-token');
    expect(FakeSocket.opened).toHaveLength(1);
    expect(FakeSocket.opened[0]).toContain('overview=link-token');
  });

  it('does not open a staff socket with no token', () => {
    const service = setup(null);
    service.connect(7);
    expect(FakeSocket.opened).toHaveLength(0);
    expect(service.status()).toBe('disabled');
  });

  it('percent-encodes the share token', () => {
    setup(null).connectShared(7, 'a b+c/d');
    expect(FakeSocket.opened[0]).toContain('overview=a%20b%2Bc%2Fd');
  });

  it('reopens when switching from a share token to a user token', () => {
    const service = setup('abc123');
    service.connectShared(7, 'link-token');
    service.connect(7);
    expect(FakeSocket.opened).toHaveLength(2);
    expect(FakeSocket.opened[1]).toContain('token=abc123');
  });
});
