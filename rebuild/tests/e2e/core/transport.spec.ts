import { test, expect } from '../../../apps/web/node_modules/@playwright/test';
import { workspaceApi, RequestFailure } from '../../../apps/web/src/api';

test('generated transport keeps auth out of URLs and preserves upload revision/key', async () => {
  const original = globalThis.fetch;
  const requests: Request[] = [];
  // Node requires absolute Request URLs; the browser's relative same-origin client
  // is tested through this narrowly scoped Request adapter, never a real server.
  const NativeRequest = globalThis.Request;
  globalThis.Request = class extends NativeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) { super(typeof input === 'string' && input.startsWith('/') ? `http://127.0.0.1:64110${input}` : input, init); }
  };
  globalThis.fetch = async input => {
    const request = input as Request; requests.push(request);
    return new Response(JSON.stringify({ id: 'synthetic' }), { headers: { 'Content-Type': 'application/json' } });
  };
  try {
    const api = workspaceApi('synthetic-token');
    await api.upload('case-fixture', 7, new File(['abc'], 'fixture.txt', { type: 'text/plain' }), null, 'synthetic-key');
    expect(requests[0].url).not.toContain('synthetic-token');
    expect(requests[0].headers.get('Authorization')).toBe('Bearer synthetic-token');
    expect(requests[0].headers.get('Idempotency-Key')).toBe('synthetic-key');
    expect(new URL(requests[0].url).searchParams.get('expected_revision')).toBe('7');
    expect((await requests[0].formData()).get('file')).toBeInstanceOf(File);
  } finally { globalThis.fetch = original; globalThis.Request = NativeRequest; }
});

test('interrupted request exposes uncertain outcome without raw transport details', async () => {
  const original = globalThis.fetch, NativeRequest = globalThis.Request;
  globalThis.Request = class extends NativeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) { super(typeof input === 'string' && input.startsWith('/') ? `http://127.0.0.1:64110${input}` : input, init); }
  };
  globalThis.fetch = async () => { throw new Error('synthetic internal detail'); };
  try { await expect(workspaceApi('synthetic-token').cases()).rejects.toThrow(RequestFailure); }
  finally { globalThis.fetch = original; globalThis.Request = NativeRequest; }
});
