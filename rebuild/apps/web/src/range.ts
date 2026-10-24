export function validateRange(start: string, end: string, size: number): { start: number; end: number } {
  if (!/^\d+$/.test(start) || !/^\d+$/.test(end)) throw new Error('Enter whole byte offsets.');
  const a = Number(start), b = Number(end);
  if (!Number.isSafeInteger(a) || !Number.isSafeInteger(b) || a < 0 || b <= a || b > size) throw new Error(`Choose 0 ≤ start < end ≤ ${size}. End is exclusive.`);
  if (b - a > 65536) throw new Error('Preview at most 65,536 bytes at a time.');
  return { start: a, end: b };
}

export function decodeRange(bytes: Uint8Array, mediaType: string, start: number, end: number, total: number) {
  const textual = /^text\//i.test(mediaType) || /(?:json|xml|javascript|csv|yaml)/i.test(mediaType);
  if (!textual) return { supported: false, text: '', warnings: ['Text preview is unsupported for this media type. Exact bytes remain available as hexadecimal.'] };
  const warnings: string[] = [];
  if (start > 0 || end < total) warnings.push('Partial byte range. A UTF-8 character may cross the selected boundary; this is not the complete document.');
  let text: string;
  try { text = new TextDecoder('utf-8', { fatal: true }).decode(bytes); }
  catch { text = new TextDecoder('utf-8').decode(bytes); warnings.push('Invalid or boundary-split UTF-8. Replacement characters appear in this preview; original bytes are unchanged.'); }
  return { supported: true, text, warnings };
}

export function hexRange(bytes: Uint8Array, offset: number): string {
  const lines: string[] = [];
  for (let i = 0; i < bytes.length; i += 16) lines.push(`${(offset + i).toString(16).padStart(8, '0')}  ${Array.from(bytes.slice(i, i + 16), b => b.toString(16).padStart(2, '0')).join(' ')}`);
  return lines.join('\n');
}
