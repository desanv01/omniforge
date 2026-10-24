import { createClient } from '../../../packages/contracts/generated/client';
import { createCase, getCase, listCases, listCaseArtifacts, uploadArtifact, readArtifactRange } from '../../../packages/contracts/generated/sdk.gen';
import type { CaseCreate, ErrorEnvelope } from '../../../packages/contracts/generated/types.gen';

export class RequestFailure extends Error {
  constructor(readonly status: number, readonly envelope?: ErrorEnvelope) {
    super(envelope?.message ?? (status ? `Request failed (${status}).` : 'Connection interrupted. The outcome may be unknown.'));
  }
}

// This client lives only as long as the in-memory authenticated workspace.
export function workspaceApi(token: string) {
  const client = createClient({ baseUrl: '', auth: () => token, redirect: 'error', cache: 'no-store' });
  async function result<T>(request: Promise<{ data?: T; error?: unknown; response?: Response }>): Promise<T> {
    try {
      const reply = await request;
      if (!reply.response?.ok || reply.data === undefined) {
        const value = reply.error;
        const envelope = value && typeof value === 'object' && 'request_id' in value && 'message' in value ? value as ErrorEnvelope : undefined;
        if (reply.error instanceof DOMException && reply.error.name === 'AbortError') throw reply.error;
        throw new RequestFailure(reply.response?.status ?? 0, envelope);
      }
      return reply.data;
    } catch (error) {
      if (error instanceof RequestFailure || (error instanceof DOMException && error.name === 'AbortError')) throw error;
      throw new RequestFailure(0);
    }
  }
  return {
    cases: (cursor?: string, signal?: AbortSignal) => result(listCases({ client, query: { cursor, limit: 20 }, signal })),
    case: (id: string, signal?: AbortSignal) => result(getCase({ client, path: { case_id: id }, signal })),
    create: (body: CaseCreate, key: string, signal?: AbortSignal) => result(createCase({ client, body, headers: { 'Idempotency-Key': key }, signal })),
    artifacts: (id: string, cursor?: string, signal?: AbortSignal) => result(listCaseArtifacts({ client, path: { case_id: id }, query: { cursor, limit: 20 }, signal })),
    upload: (id: string, revision: number, file: File, capturedAt: string | null, key: string, signal?: AbortSignal) => result(uploadArtifact({ client, path: { case_id: id }, body: { file }, query: { expected_revision: revision, captured_at: capturedAt }, headers: { 'Idempotency-Key': key }, signal })),
    // Generated binary DTO is Blob|File; explicit blob parsing preserves exact bytes.
    range: async (id: string, start: number, end: number, signal?: AbortSignal) => {
      const blob = await result(readArtifactRange({ client, path: { association_id: id }, query: { start_byte: start, end_byte: end }, parseAs: 'blob', signal }));
      const bytes = new Uint8Array(await blob.arrayBuffer());
      if (bytes.byteLength !== end - start) throw new Error('Returned byte count differs from the requested half-open range.');
      return bytes;
    },
  };
}
