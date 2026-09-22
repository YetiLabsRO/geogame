import { extractNfcToken } from './nfc.service';

/**
 * mobile-app 2.11 — the token extractor is shared across every NFC
 * transport (Web NFC, the native bridge, manual/QR entry), so every
 * capture path agrees on the same token for a given tag.
 */
describe('extractNfcToken', () => {
  it('extracts the token from an absolute URL record', () => {
    expect(
      extractNfcToken([{ type: 'url', payload: 'https://cercetador.albascout.ro/nfc/abc123/' }]),
    ).toBe('abc123');
  });

  it('extracts the token from a relative URL path', () => {
    expect(extractNfcToken([{ type: 'url', payload: '/nfc/abc123/' }])).toBe('abc123');
  });

  it('extracts the token from the custom scheme', () => {
    expect(extractNfcToken([{ type: 'url', payload: 'cercetador://nfc/abc123' }])).toBe('abc123');
  });

  it('accepts a plain text token record', () => {
    expect(extractNfcToken([{ type: 'text', payload: 'abc123' }])).toBe('abc123');
  });

  it('trims whitespace around a plain text token', () => {
    expect(extractNfcToken([{ payload: '  abc123  ' }])).toBe('abc123');
  });

  it('decodes a URL-encoded token segment', () => {
    expect(extractNfcToken([{ payload: '/nfc/ab%20c123/' }])).toBe('ab c123');
  });

  it('ignores query strings and fragments after the token', () => {
    expect(extractNfcToken([{ payload: '/nfc/abc123/?src=qr#top' }])).toBe('abc123');
  });

  it('skips a record that does not resolve to a token and tries the next one', () => {
    expect(
      extractNfcToken([
        { type: 'text', payload: '' },
        { type: 'url', payload: 'https://cercetador.albascout.ro/nfc/xyz789' },
      ]),
    ).toBe('xyz789');
  });

  it('rejects an unrelated absolute URL rather than treating it as a token', () => {
    expect(extractNfcToken([{ payload: 'https://example.com/other' }])).toBeNull();
  });

  it('returns null for an empty record list', () => {
    expect(extractNfcToken([])).toBeNull();
  });

  it('returns null when every record is blank', () => {
    expect(extractNfcToken([{ payload: '' }, { payload: '   ' }])).toBeNull();
  });
});
