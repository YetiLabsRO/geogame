import { provideZonelessChangeDetection } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { DialogService } from './confirm.service';

/** The mounted dialog's panel, or null if none is open. */
function panel(): HTMLElement | null {
  return document.querySelector('.app-confirm-panel');
}

function buttons(): HTMLButtonElement[] {
  return Array.from(document.querySelectorAll('.app-confirm-panel__actions .btn'));
}

/** Click the button whose text contains `label`. */
function click(label: string): void {
  const match = buttons().find((b) => (b.textContent ?? '').trim().includes(label));
  if (!match) throw new Error(`No "${label}" button among: ${buttons().map((b) => b.textContent)}`);
  match.click();
}

/** Let the component render / tear down before asserting on the DOM. */
function settle(): Promise<void> {
  return TestBed.inject(DialogService) && new Promise((r) => setTimeout(r, 0));
}

describe('DialogService', () => {
  let dialogs: DialogService;

  beforeEach(async () => {
    TestBed.configureTestingModule({ providers: [provideZonelessChangeDetection()] });
    dialogs = TestBed.inject(DialogService);
  });

  afterEach(() => {
    document.querySelectorAll('.app-confirm-panel').forEach((el) => el.remove());
    document.body.style.overflow = '';
  });

  describe('confirm', () => {
    it('resolves true when confirmed and false when cancelled', async () => {
      const yes = dialogs.confirm({ title: 'Go?', message: 'Really?' });
      await settle();
      click('Confirm');
      expect(await yes).toBe(true);

      const no = dialogs.confirm({ title: 'Go?', message: 'Really?' });
      await settle();
      click('Cancel');
      expect(await no).toBe(false);
    });

    it('holds the confirm control until the required phrase is typed', async () => {
      const answer = dialogs.confirm({
        title: 'Delete?',
        message: 'Gone for good.',
        danger: true,
        requireTyping: 'my-game',
      });
      await settle();
      const confirm = buttons().find((b) => b.classList.contains('btn-danger'))!;
      expect(confirm.disabled).toBe(true);

      const input = document.querySelector<HTMLInputElement>('.app-confirm-panel__field input')!;
      input.value = 'my-game';
      input.dispatchEvent(new Event('input'));
      await settle();
      expect(confirm.disabled).toBe(false);

      confirm.click();
      expect(await answer).toBe(true);
    });
  });

  describe('alert', () => {
    it('states something and offers no way to decline', async () => {
      const acknowledged = dialogs.alert({ title: 'Heads up', message: 'It happened.' });
      await settle();
      expect(buttons()).toHaveLength(1);
      expect(buttons()[0].textContent?.trim()).toBe('OK');
      click('OK');
      expect(await acknowledged).toBeUndefined();
    });
  });

  describe('prompt', () => {
    it('resolves the typed text', async () => {
      const answer = dialogs.prompt({
        title: 'Name it',
        message: 'What should it be called?',
        initialValue: 'draft',
      });
      await settle();
      const input = document.querySelector<HTMLInputElement>('.app-confirm-panel__field input')!;
      expect(input.value).toBe('draft');
      input.value = 'the real name';
      input.dispatchEvent(new Event('input'));
      await settle();
      click('Confirm');
      expect(await answer).toBe('the real name');
    });

    it('resolves null when cancelled — "" is something a person could type', async () => {
      const answer = dialogs.prompt({ title: 'Name it', message: 'Well?' });
      await settle();
      click('Cancel');
      expect(await answer).toBeNull();
    });
  });

  describe('semantics and the keyboard', () => {
    it('announces a destructive dialog as an alertdialog and the rest as a dialog', async () => {
      const danger = dialogs.confirm({ title: 'Delete', message: '!', danger: true });
      await settle();
      expect(panel()?.getAttribute('role')).toBe('alertdialog');
      click('Confirm');
      await danger;

      const plain = dialogs.confirm({ title: 'Save', message: '?' });
      await settle();
      expect(panel()?.getAttribute('role')).toBe('dialog');
      click('Confirm');
      await plain;
    });

    it('labels and describes itself by its own title and message', async () => {
      const open = dialogs.confirm({ title: 'A title', message: 'A message' });
      await settle();
      const el = panel()!;
      expect(el.getAttribute('aria-modal')).toBe('true');
      expect(document.getElementById(el.getAttribute('aria-labelledby')!)?.textContent).toBe(
        'A title',
      );
      expect(document.getElementById(el.getAttribute('aria-describedby')!)?.textContent).toBe(
        'A message',
      );
      click('Confirm');
      await open;
    });

    it('cancels on Escape', async () => {
      const answer = dialogs.confirm({ title: 'Go?', message: '?' });
      await settle();
      panel()!.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }),
      );
      expect(await answer).toBe(false);
    });

    it('cancels on a backdrop click', async () => {
      const answer = dialogs.confirm({ title: 'Go?', message: '?' });
      await settle();
      document.querySelector<HTMLElement>('.app-confirm-backdrop')!.click();
      expect(await answer).toBe(false);
    });

    it('stops the page behind from scrolling, and lets it again on close', async () => {
      const answer = dialogs.confirm({ title: 'Go?', message: '?' });
      await settle();
      expect(document.body.style.overflow).toBe('hidden');
      click('Confirm');
      await answer;
      await settle();
      expect(document.body.style.overflow).not.toBe('hidden');
    });

    it('returns focus to whatever had it before', async () => {
      const opener = document.createElement('button');
      document.body.appendChild(opener);
      opener.focus();
      expect(document.activeElement).toBe(opener);

      const answer = dialogs.confirm({ title: 'Go?', message: '?' });
      await settle();
      expect(panel()!.contains(document.activeElement)).toBe(true);

      click('Confirm');
      await answer;
      await settle();
      expect(document.activeElement).toBe(opener);
      opener.remove();
    });

    it('tears the dialog out of the DOM once answered', async () => {
      const answer = dialogs.confirm({ title: 'Go?', message: '?' });
      await settle();
      expect(panel()).not.toBeNull();
      click('Confirm');
      await answer;
      await settle();
      expect(panel()).toBeNull();
    });
  });
});
