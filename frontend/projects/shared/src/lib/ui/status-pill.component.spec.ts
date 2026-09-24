import { provideZonelessChangeDetection } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';

import { StatusPillComponent, humaniseStatus, statusStyle } from './status-pill.component';

describe('humaniseStatus', () => {
  it('turns a constant into something a person would write', () => {
    expect(humaniseStatus('OPEN_FOR_PARTICIPANTS')).toBe('Open for participants');
    expect(humaniseStatus('IN_PROGRESS')).toBe('In progress');
    expect(humaniseStatus('RUNNING')).toBe('Running');
  });

  it('copes with dashes, runs of separators and surrounding space', () => {
    expect(humaniseStatus('  awaiting--review  ')).toBe('Awaiting review');
  });

  it('gives back nothing for nothing, rather than an empty pill with a stray cap', () => {
    expect(humaniseStatus('')).toBe('');
  });
});

describe('statusStyle', () => {
  it('reads a known status as its label, never as its constant', () => {
    expect(statusStyle('OPEN_FOR_PARTICIPANTS')).toEqual({
      label: 'Open for participants',
      tone: 'info',
    });
    expect(statusStyle('RUNNING').tone).toBe('success');
    expect(statusStyle('FINISHED').tone).toBe('muted');
  });

  it('humanises a status it has never seen rather than printing the raw constant', () => {
    expect(statusStyle('SOME_NEW_STATE')).toEqual({
      label: 'Some new state',
      tone: 'neutral',
    });
  });
});

describe('StatusPillComponent', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideZonelessChangeDetection()] });
  });

  function render(inputs: Record<string, unknown>): HTMLElement {
    const fixture = TestBed.createComponent(StatusPillComponent);
    for (const [key, value] of Object.entries(inputs)) {
      fixture.componentRef.setInput(key, value);
    }
    fixture.detectChanges();
    return fixture.nativeElement.querySelector('.status-pill');
  }

  it('shows the label and carries the tone', () => {
    const pill = render({ status: 'OPEN_FOR_PARTICIPANTS' });
    expect(pill.textContent?.trim()).toBe('Open for participants');
    expect(pill.getAttribute('data-tone')).toBe('info');
  });

  it('lets a caller override the tone and the label', () => {
    const pill = render({ status: 'RUNNING', tone: 'danger', label: 'Overrun' });
    expect(pill.textContent?.trim()).toBe('Overrun');
    expect(pill.getAttribute('data-tone')).toBe('danger');
  });

  it('never shows an underscore', () => {
    for (const status of ['OPEN_FOR_PARTICIPANTS', 'AWAITING_REVIEW', 'A_MADE_UP_ONE']) {
      expect(render({ status }).textContent).not.toContain('_');
    }
  });
});
