import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * The app owns its dialogs. The browser's `confirm`, `alert` and `prompt`
 * arrive unstyled, unreadable in dark mode and prefixed with the host name,
 * and they were asking the most consequential questions the app ever asks.
 * `DialogService` replaced them — this keeps them gone.
 */

/** Where the workspace root sits relative to this file. */
const ROOT = join(__dirname, '..', '..', '..', '..', '..');
const SCANNED = ['projects/shared/src', 'projects/staff/src', 'projects/player/src'];

/**
 * The three files that *are* the replacement: the dialog component, the
 * service whose methods are named after what they replace, and this guard,
 * whose prose names them too.
 */
const EXEMPT = [
  'projects/shared/src/lib/ui/confirm-dialog.component.ts',
  'projects/shared/src/lib/ui/confirm.service.ts',
  'projects/shared/src/lib/ui/native-dialogs.guard.spec.ts',
];

/**
 * An Angular template's `confirm(x)` resolves to a component member, not to
 * the global — so the inline `template:` and `styles:` blocks are not code
 * this rule applies to. Drop them before scanning.
 */
function stripInlineBlocks(source: string): string {
  return source.replace(/(template|styles):\s*`[\s\S]*?`(?=\s*[,}])/g, (block) =>
    block.replace(/[^\n]/g, ' '),
  );
}

/** `protected confirm(s: X)` declares a member; it does not call the global. */
const DECLARATION = /(?:protected|private|public|static|readonly|async|function|get|set)\s+$/;
const CALL = /(?<![.\w$])(confirm|alert|prompt)\s*\(/g;

function tsFilesUnder(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...tsFilesUnder(full));
    } else if (entry.endsWith('.ts')) {
      out.push(full);
    }
  }
  return out;
}

function nativeDialogCalls(): string[] {
  const offences: string[] = [];
  for (const scanned of SCANNED) {
    for (const file of tsFilesUnder(join(ROOT, scanned))) {
      const rel = relative(ROOT, file).replaceAll('\\', '/');
      if (EXEMPT.includes(rel)) continue;
      const lines = stripInlineBlocks(readFileSync(file, 'utf8')).split('\n');
      lines.forEach((line, i) => {
        // `window.confirm(...)` is unambiguous wherever it appears.
        for (const name of ['confirm', 'alert', 'prompt']) {
          if (new RegExp(`\\b(?:window|globalThis|self)\\.${name}\\s*\\(`).test(line)) {
            offences.push(`${rel}:${i + 1} — window.${name}(`);
          }
        }
        for (const match of line.matchAll(CALL)) {
          if (DECLARATION.test(line.slice(0, match.index))) continue;
          offences.push(`${rel}:${i + 1} — ${match[1]}(`);
        }
      });
    }
  }
  return offences;
}

describe('the app owns its dialogs', () => {
  it('finds no native confirm, alert or prompt in either SPA or the shared library', () => {
    expect(nativeDialogCalls()).toEqual([]);
  });

  it('would notice one if it came back', () => {
    const planted = stripInlineBlocks(
      'class X {\n  go() {\n    if (!confirm("really?")) return;\n  }\n}\n',
    );
    expect([...planted.matchAll(CALL)].map((m) => m[1])).toEqual(['confirm']);
  });

  it('does not mistake a component member for the global', () => {
    // pending-queue declares `confirm(s)` and its template calls it; neither
    // is the browser's dialog.
    const component = [
      "@Component({ template: `<button (click)=\"confirm(s)\">Confirm</button>`, })",
      'export class Q {',
      '  protected confirm(s: Submission): void {}',
      '}',
    ].join('\n');
    const scannable = stripInlineBlocks(component);
    const hits = [...scannable.matchAll(CALL)].filter(
      (m) => !DECLARATION.test(scannable.slice(0, m.index).split('\n').pop() ?? ''),
    );
    expect(hits).toEqual([]);
  });
});
