import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import type { ArtifactAssociation, ArtifactPage, Case, CasePage } from '../../../packages/contracts/generated/types.gen';
import { workspaceApi, RequestFailure } from './api';
import { decodeRange, hexRange, validateRange } from './range';

type Api = ReturnType<typeof workspaceApi>;
function message(error: unknown) { return error instanceof Error ? error.message : 'The request could not be completed.'; }
function Failure({ error }: { error: unknown }) {
  return <div role="alert" className="notice error"><strong>{message(error)}</strong>{error instanceof RequestFailure && error.envelope ? <small>{error.envelope.code} · Request {error.envelope.request_id}{error.status === 409 ? ' · Refresh the case before trying a new operation.' : ''}</small> : null}</div>;
}
const date = (value: string | null | undefined) => value ? new Date(value).toLocaleString() : 'Not recorded';

export function App() {
  const [api, setApi] = useState<Api | null>(null);
  return api ? <Workspace api={api} disconnect={() => setApi(null)} /> : <Connect connect={setApi} />;
}

function Connect({ connect }: { connect: (api: Api) => void }) {
  const token = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState<unknown>(null);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  async function submit(event: FormEvent) {
    event.preventDefault(); const value = token.current?.value.trim(); if (!value) return;
    const client = workspaceApi(value); controller.current = new AbortController(); setBusy(true); setError(null);
    try { await client.cases(undefined, controller.current.signal); if (token.current) token.current.value = ''; connect(client); }
    catch (failure) { setError(failure); setBusy(false); }
  }
  return <main className="connection"><div className="connect-story"><div className="brand"><span className="mark">O/F</span> OmniForge</div><div><span className="eyebrow">LOCAL EVIDENCE WORKSPACE</span><h1>A clear trail.<br />From source<br />to understanding.</h1><p>Keep your cases, original artifacts, and exact evidence together.</p></div><span className="footnote">Your sources. Your local workspace.</span></div><div className="connect-panel"><form onSubmit={submit}><span className="eyebrow">01 / CONNECT</span><h2>Open your workspace</h2><p>Connect to the local API with your prototype access token.</p><div className="endpoint"><span>Local API</span><code>127.0.0.1:64111</code></div><label htmlFor="token">Access token</label><input id="token" ref={token} type="password" required autoComplete="off" spellCheck={false} disabled={busy} /><p className="helper">Held in memory for this session. Reloading or disconnecting clears access.</p>{error ? <Failure error={error} /> : null}<button className="primary wide" disabled={busy}>{busy ? 'Connecting…' : 'Connect to workspace →'}</button><div className="prototype"><strong>Local prototype</strong><p>Cases and artifact inspection only. Provider setup, including DeepSeek, and automated runs are planned for a later phase.</p></div></form></div></main>;
}

function Workspace({ api, disconnect }: { api: Api; disconnect: () => void }) {
  const [page, setPage] = useState<CasePage>({ items: [], next_cursor: null });
  const [selected, select] = useState<string | null>(null), [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(true), [error, setError] = useState<unknown>(null);
  const lifetime = useRef(new AbortController());
  const epoch = useRef(0);
  useEffect(() => { lifetime.current = new AbortController(); void load(false); return () => { lifetime.current.abort(); epoch.current++; }; }, [api]);
  async function load(more: boolean) {
    const request = ++epoch.current; setBusy(true); setError(null);
    try { const next = await api.cases(more ? page.next_cursor ?? undefined : undefined, lifetime.current.signal); if (request === epoch.current) setPage(old => ({ ...next, items: more ? [...old.items, ...next.items] : next.items })); }
    catch (failure) { if (!lifetime.current.signal.aborted && request === epoch.current) setError(failure); }
    finally { if (request === epoch.current) setBusy(false); }
  }
  return <div className="workspace"><aside className="sidebar"><a className="brand" href="#cases" onClick={() => { select(null); setCreating(false); }}><span className="mark">O/F</span> OmniForge</a><span className="eyebrow section-label">WORKSPACE</span><button className="nav active" onClick={() => { select(null); setCreating(false); }}><span>Cases</span><span>{page.items.length}{page.next_cursor ? '+' : ''}</span></button><div className="side-note"><span className="eyebrow">COMING LATER</span><p>Provider connections<br />Automated runs</p></div><div className="session"><span className="session-dot" />Local session<button className="text-button" onClick={disconnect}>Disconnect</button></div></aside><div className="body"><header className="topbar"><span>Workspace <span className="slash">/</span> Cases {selected ? <><span className="slash">/</span> Detail</> : null}</span><span className="prototype-tag">LOCAL PROTOTYPE</span></header><main id="cases" className="content">{creating ? <CreateCase api={api} cancel={() => setCreating(false)} created={item => { setPage(old => ({ ...old, items: [item, ...old.items.filter(c => c.id !== item.id)] })); select(item.id); setCreating(false); }} /> : selected ? <CaseDetail key={selected} api={api} id={selected} back={() => select(null)} /> : <><div className="page-heading"><div><span className="eyebrow">YOUR INVESTIGATIONS</span><h1>Cases<span className="heading-dot">.</span></h1><p>A place for every question. A source for every finding.</p></div><button className="primary" onClick={() => setCreating(true)}>+ New case</button></div><div className="section-heading"><h2>Case library</h2><button onClick={() => void load(false)} disabled={busy}>Refresh</button></div>{error ? <Failure error={error} /> : null}{busy && !page.items.length ? <div className="empty" role="status">Loading cases…</div> : !page.items.length && !error ? <div className="empty"><span className="empty-number">01</span><h2>Start with a question</h2><p>Create a case, then import the sources you want to inspect.</p><button onClick={() => setCreating(true)}>Create your first case →</button></div> : <div className="case-grid">{page.items.map(item => <button className="case-card" key={item.id} onClick={() => select(item.id)}><span className="card-top"><span className="pill">{item.status ?? 'open'}</span><span aria-hidden="true">↗</span></span><h2>{item.title}</h2><p>{item.objective || 'No objective recorded.'}</p><span className="card-meta">Updated {date(item.updated_at)}<span>Rev {item.revision}</span></span></button>)}</div>}{page.next_cursor ? <div className="pagination"><span>Partial list · more cases available</span><button disabled={busy} onClick={() => void load(true)}>{busy ? 'Loading…' : 'Load more cases'}</button></div> : null}</>}</main><footer className="workspace-footer">OmniForge <span>Evidence, with context.</span></footer></div></div>;
}

function CreateCase({ api, cancel, created }: { api: Api; cancel: () => void; created: (item: Case) => void }) {
  const [title, setTitle] = useState(''), [objective, setObjective] = useState('');
  const [error, setError] = useState<unknown>(null), [busy, setBusy] = useState(false);
  const operation = useRef<{ payload: string; key: string } | null>(null), controller = useRef(new AbortController());
  useEffect(() => { controller.current = new AbortController(); return () => controller.current.abort(); }, []);
  async function submit(event: FormEvent) {
    event.preventDefault(); const body = { title: title.trim(), objective }; const payload = JSON.stringify(body);
    if (operation.current?.payload !== payload) operation.current = { payload, key: crypto.randomUUID() };
    setBusy(true); setError(null);
    try { created(await api.create(body, operation.current!.key, controller.current.signal)); }
    catch (failure) { if (!controller.current.signal.aborted) setError(failure); }
    finally { setBusy(false); }
  }
  return <><button className="text-button back" onClick={cancel}>← All cases</button><div className="page-heading"><div><span className="eyebrow">A NEW LINE OF INQUIRY</span><h1>Create a case</h1><p>Give your work a clear name and a useful objective.</p></div></div><form className="editor-form" onSubmit={submit}><label htmlFor="title">Case title</label><input id="title" value={title} onChange={e => setTitle(e.target.value)} required maxLength={200} disabled={busy} /><label htmlFor="objective">Objective <span className="optional">optional</span></label><textarea id="objective" value={objective} onChange={e => setObjective(e.target.value)} maxLength={4000} rows={5} disabled={busy} /><p className="helper">Policy profile: local-read-only-v1. Creating a case does not start a provider or run.</p>{error ? <Failure error={error} /> : null}<div className="form-actions"><button type="button" onClick={cancel} disabled={busy}>Cancel</button><button className="primary" disabled={busy || !title.trim()}>{busy ? 'Saving…' : error instanceof RequestFailure && error.status === 0 ? 'Retry same operation' : 'Create case'}</button></div></form></>;
}

function CaseDetail({ api, id, back }: { api: Api; id: string; back: () => void }) {
  const [item, setItem] = useState<Case | null>(null), [page, setPage] = useState<ArtifactPage>({ items: [], next_cursor: null });
  const [error, setError] = useState<unknown>(null), [busy, setBusy] = useState(true), [artifact, select] = useState<ArtifactAssociation | null>(null), [importing, setImporting] = useState(false);
  const [uploadBusy, setUploadBusy] = useState(false);
  const controller = useRef(new AbortController()), epoch = useRef(0);
  useEffect(() => { controller.current = new AbortController(); void refresh(); return () => { controller.current.abort(); epoch.current++; }; }, [api, id]);
  async function refresh(more = false) {
    const request = ++epoch.current; setBusy(true); setError(null); if (!more) select(null);
    try { const [current, artifacts] = await Promise.all([api.case(id, controller.current.signal), api.artifacts(id, more ? page.next_cursor ?? undefined : undefined, controller.current.signal)]); if (request === epoch.current) { setItem(current); setPage(old => ({ ...artifacts, items: more ? [...old.items, ...artifacts.items] : artifacts.items })); } }
    catch (failure) { if (!controller.current.signal.aborted && request === epoch.current) setError(failure); }
    finally { if (request === epoch.current) setBusy(false); }
  }
  return <><button className="text-button back" onClick={back}>← All cases</button>{error ? <Failure error={error} /> : null}{!item ? <div className="empty" role="status">{busy ? 'Loading case and grants…' : 'Case unavailable.'}<button onClick={() => void refresh()} disabled={busy}>Retry</button></div> : <><div className="page-heading"><div><span className="eyebrow">CASE / {item.id.slice(0, 8)}</span><h1>{item.title}</h1><p>{item.objective || 'No objective recorded.'}</p></div><button className="primary" disabled={busy || uploadBusy} onClick={() => setImporting(v => !v)}>{importing ? 'Close import' : '+ Import artifact'}</button></div><div className="case-facts"><span><span className="pill">{item.status ?? 'open'}</span></span><span>Revision <strong>{item.revision}</strong></span><span>Updated {date(item.updated_at)}</span><span>Policy <code>{item.policy_profile_ref}</code></span></div>{importing ? <ImportArtifact api={api} item={item} onBusy={setUploadBusy} done={() => { setImporting(false); void refresh(); }} /> : null}<div className="evidence-layout"><section className="artifact-section"><div className="section-heading"><h2>Source artifacts <span className="count">{page.items.length}{page.next_cursor ? '+' : ''}</span></h2><button disabled={busy} onClick={() => void refresh()}>Refresh</button></div><p className="section-caption">Original bytes and their recorded origins.</p>{busy && !page.items.length ? <div className="empty" role="status">Loading artifacts…</div> : !page.items.length ? <div className="empty"><span className="empty-number">∅</span><h2>No artifacts yet</h2><p>Import a source to inspect its bytes and provenance.</p></div> : <div className="artifact-list">{page.items.map(entry => <button className={`artifact-row ${artifact?.id === entry.id ? 'selected' : ''}`} key={entry.id} onClick={() => select(entry)}><span className="file-symbol" aria-hidden="true">TXT</span><span className="artifact-name"><strong>{entry.original_name}</strong><small>{entry.media_type} · {entry.bytes.toLocaleString()} bytes</small><small>Source {entry.source_id}</small></span><span className={`pill ${entry.publication_status !== 'committed' ? 'warning' : ''}`}>{entry.publication_status}</span></button>)}</div>}{page.next_cursor ? <div className="pagination"><span>Partial list</span><button disabled={busy} onClick={() => void refresh(true)}>Load more artifacts</button></div> : null}</section><section className="inspector" aria-label="Artifact inspector">{artifact ? <Inspector key={artifact.id} api={api} artifact={artifact} /> : <div className="inspector-placeholder"><span className="eyebrow">EVIDENCE INSPECTOR</span><h2>Every byte has context.</h2><p>Select an artifact to inspect an exact range, its original source, and recorded metadata.</p><span className="range-illustration" aria-hidden="true">[ start ───── end )</span></div>}</section></div></>}</>;
}

function ImportArtifact({ api, item, done, onBusy }: { api: Api; item: Case; done: () => void; onBusy: (busy: boolean) => void }) {
  const [file, setFile] = useState<File | null>(null), [captured, setCaptured] = useState(''), [busy, setBusy] = useState(false), [error, setError] = useState<unknown>(null);
  const operation = useRef<{ file: File; captured: string; revision: number; key: string } | null>(null), controller = useRef(new AbortController());
  useEffect(() => () => controller.current.abort(), []);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!file) return;
    if (file.size > 25 * 1024 * 1024) { setError(new Error('Choose a file at most 25 MiB.')); return; }
    if (captured && (!/(Z|[+-]\d{2}:\d{2})$/i.test(captured) || !Number.isFinite(Date.parse(captured)))) { setError(new Error('Use an ISO timestamp with a timezone, such as 2026-10-23T10:00:00+08:00.')); return; }
    if (operation.current?.file !== file || operation.current?.captured !== captured || operation.current?.revision !== item.revision) operation.current = { file, captured, revision: item.revision, key: crypto.randomUUID() };
    controller.current = new AbortController(); setBusy(true); onBusy(true); setError(null);
    try { await api.upload(item.id, operation.current.revision, file, captured || null, operation.current.key, controller.current.signal); done(); }
    catch (failure) { setError(controller.current.signal.aborted ? new Error('Upload interrupted. Publication may have completed. Refresh artifacts, or retry the unchanged operation using its same key.') : failure); }
    finally { setBusy(false); onBusy(false); }
  }
  return <form className="import-form" onSubmit={submit}><div><h2>Import an original source</h2><p className="helper">Up to 25 MiB. Saved against case revision {item.revision}.</p></div><label htmlFor="file">Source file</label><input id="file" type="file" required disabled={busy} onChange={e => setFile(e.target.files?.[0] ?? null)} /><label htmlFor="captured">Captured at <span className="optional">optional · timezone required</span></label><input id="captured" value={captured} onChange={e => setCaptured(e.target.value)} placeholder="2026-10-23T10:00:00+08:00" disabled={busy} /><p className="helper">Leave blank if unknown. Import time and capture time are separate.</p>{error ? <Failure error={error} /> : null}<div className="form-actions">{busy ? <button type="button" onClick={() => controller.current.abort()}>Interrupt upload</button> : null}<button className="primary" disabled={busy || !file}>{busy ? 'Importing…' : error ? 'Retry import' : 'Import artifact'}</button></div></form>;
}

function Inspector({ api, artifact }: { api: Api; artifact: ArtifactAssociation }) {
  const [start, setStart] = useState('0'), [end, setEnd] = useState(String(Math.min(artifact.bytes, 4096))), [mode, setMode] = useState<'text' | 'hex'>('text');
  const [preview, setPreview] = useState<{ bytes: Uint8Array; start: number; end: number } | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<unknown>(null);
  const controller = useRef<AbortController | null>(null), epoch = useRef(0);
  useEffect(() => () => { epoch.current++; controller.current?.abort(); }, []);
  async function read(event: FormEvent) {
    event.preventDefault(); controller.current?.abort(); const request = ++epoch.current; setError(null); setPreview(null);
    try { const bounds = validateRange(start, end, artifact.bytes); controller.current = new AbortController(); setBusy(true); const bytes = await api.range(artifact.id, bounds.start, bounds.end, controller.current.signal); if (request === epoch.current) setPreview({ bytes, ...bounds }); }
    catch (failure) { if (request === epoch.current) setError(controller.current?.signal.aborted ? new Error('Range read interrupted. No preview is shown.') : failure); }
    finally { if (request === epoch.current) setBusy(false); }
  }
  const decoded = preview ? decodeRange(preview.bytes, artifact.media_type, preview.start, preview.end, artifact.bytes) : null;
  return <><div className="inspector-head"><span className="eyebrow">EVIDENCE INSPECTOR</span><h2>{artifact.original_name}</h2><span className="pill">{artifact.publication_status}</span></div><dl className="metadata"><dt>SHA-256 · full artifact</dt><dd className="hash">{artifact.sha256}</dd><dt>Source ID</dt><dd>{artifact.source_id}</dd><dt>Captured at</dt><dd>{date(artifact.captured_at)}</dd><dt>Imported at</dt><dd>{date(artifact.imported_at)}</dd><dt>Saved size / type</dt><dd>{artifact.bytes.toLocaleString()} bytes / {artifact.media_type}</dd><dt>Association / revision</dt><dd>{artifact.id} / {artifact.revision}</dd></dl>{artifact.warnings?.map((warning, i) => <div className="notice" key={i}>{warning}</div>)}{artifact.publication_status !== 'committed' ? <div className="notice">Publication {artifact.publication_status}. Byte preview is unavailable until committed. Refresh the artifact list for current status.</div> : artifact.bytes === 0 ? <div className="notice">Complete empty artifact · 0 bytes. There is no nonempty byte range to read.</div> : <form className="range-form" onSubmit={read}><h3>Exact byte range</h3><p className="helper">Start inclusive, end exclusive. Preview up to 65,536 bytes.</p><div className="range-inputs"><label>Start<input inputMode="numeric" value={start} onChange={e => setStart(e.target.value)} disabled={busy} /></label><label>End<input inputMode="numeric" value={end} onChange={e => setEnd(e.target.value)} disabled={busy} /></label><button className="primary" disabled={busy}>{busy ? 'Reading…' : 'Read range'}</button></div>{busy ? <button type="button" onClick={() => controller.current?.abort()}>Interrupt read</button> : null}</form>}{error ? <Failure error={error} /> : null}{preview && decoded ? <div className="preview"><div className="preview-toolbar"><span>Bytes [{preview.start}, {preview.end}) · {preview.bytes.length} bytes</span><div><button aria-pressed={mode === 'text'} onClick={() => setMode('text')}>Text</button><button aria-pressed={mode === 'hex'} onClick={() => setMode('hex')}>Hex</button></div></div>{decoded.warnings.map((warning, i) => <div className="notice" key={i}>{warning}</div>)}<pre tabIndex={0} aria-label="Exact range preview">{mode === 'hex' ? hexRange(preview.bytes, preview.start) : decoded.supported ? decoded.text : 'Unsupported text preview. Select Hex to inspect the exact bytes.'}</pre></div> : null}</>;
}
