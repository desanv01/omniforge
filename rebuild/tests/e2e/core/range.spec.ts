import { test, expect } from '../../../apps/web/node_modules/@playwright/test';
import { validateRange, decodeRange, hexRange } from '../../../apps/web/src/range';

test('range bounds preserve half-open semantics and reject unsafe or oversized previews', () => {
  expect(validateRange('0', '3', 3)).toEqual({ start: 0, end: 3 });
  expect(() => validateRange('0', '4', 3)).toThrow();
  for (const [start, end] of [['0', '0'], ['-1', '2'], ['1.5', '2'], ['0', '65537'], ['0', '9007199254740993']]) {
    expect(() => validateRange(start, end, 100000)).toThrow();
  }
});

test('UTF-8 boundaries and unsupported media never imply complete decoded evidence', () => {
  const complete = decodeRange(new TextEncoder().encode('é'), 'text/plain', 0, 2, 2);
  expect(complete.text).toBe('é'); expect(complete.warnings).toEqual([]);
  const split = decodeRange(new Uint8Array([0xa9]), 'text/plain', 1, 2, 2);
  expect(split.warnings).toHaveLength(2); expect(split.text).toBe('�');
  expect(decodeRange(new Uint8Array([0]), 'image/png', 0, 1, 1).supported).toBe(false);
  expect(hexRange(new Uint8Array([0, 255, 16]), 32)).toBe('00000020  00 ff 10');
});
