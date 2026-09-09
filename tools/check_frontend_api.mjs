// Run: node --test tools/check_frontend_api.mjs
// Compile the real client in memory; no build artifacts or browser required.
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';
import { test } from 'node:test';

const require = createRequire(new URL('../frontend/package.json', import.meta.url));
const ts = require('typescript');
const compile = source => `data:text/javascript;base64,${Buffer.from(ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2023, module: ts.ModuleKind.ESNext },
}).outputText).toString('base64')}`;
const errors = compile(await readFile(new URL('../frontend/src/api/errors.ts', import.meta.url), 'utf8'));
const source = (await readFile(new URL('../frontend/src/api/client.ts', import.meta.url), 'utf8'))
  .replace('"./errors"', JSON.stringify(errors))
  .replace('import.meta.env.VITE_API_BASE_URL', 'undefined');
const client = await import(compile(source));
const valid = JSON.parse(await readFile(new URL('../frontend/public/fixtures/binding_bound.json', import.meta.url), 'utf8'));
let lastRequest;
class FakeXHR {
  upload = {};
  open(method, url) { this.method = method; this.url = url; }
  send(form) { this.form = form; lastRequest = this; }
  finish(body, status = 200) { this.status = status; this.responseText = body; this.onload(); }
}
const originalXHR = globalThis.XMLHttpRequest;
const originalFetch = globalThis.fetch;
globalThis.XMLHttpRequest = FakeXHR;
process.on('exit', () => { globalThis.XMLHttpRequest = originalXHR; globalThis.fetch = originalFetch; });
const document = new File(['synthetic'], 'sample.png', { type: 'image/png' });

test('upload completion reaches processing before the server responds', async () => {
  const progress = [];
  const pending = client.verifyPan(document, value => progress.push(value));
  lastRequest.upload.onload();
  assert.deepEqual(progress, [1]);
  assert.equal(lastRequest.timeout, 180_000);
  lastRequest.finish(JSON.stringify(valid));
  assert.equal((await pending).identity_binding, 'BOUND');
});

test('HTML, empty and invalid successful verification responses reject cleanly', async () => {
  for (const body of ['', '<html>proxy fallback</html>', '{}', JSON.stringify({ ...valid, verdict: 'VERIFIED' }),
    JSON.stringify({ ...valid, reasons: [{ code: 'TEST', tier: 'unknown', message: 'test' }] })]) {
    const pending = client.verifyPan(document);
    lastRequest.finish(body);
    await assert.rejects(pending, error => error instanceof client.ApiError && error.status === 502);
  }
});

test('FastAPI validation errors retain their human-readable messages', async () => {
  const pending = client.verifyPan(document);
  lastRequest.finish(JSON.stringify({ detail: [{ msg: 'A valid image is required' }] }), 422);
  await assert.rejects(pending, error => error.status === 422 && error.detail === 'A valid image is required');
});

test('timeout and abort settle the upload promise instead of leaving a spinner forever', async () => {
  for (const event of ['ontimeout', 'onabort']) {
    const pending = client.verifyPan(document);
    lastRequest[event]();
    await assert.rejects(pending, error => error instanceof client.ApiError && error.status === 0);
  }
});

test('face requests include every frame, consent and the selected challenge', async () => {
  const frames = [document, document, document];
  const pending = client.verifyFace({ idPhoto: document, frames, consentSubject: 'test-subject', challenge: 'head_turn' });
  assert.equal(lastRequest.url, 'http://localhost:8000/verify/face');
  assert.equal(lastRequest.form.getAll('frames').length, 3);
  assert.equal(lastRequest.form.get('challenge'), 'head_turn');
  assert.equal(lastRequest.form.get('consent_subject'), 'test-subject');
  lastRequest.finish(JSON.stringify(valid));
  await pending;
});

test('Aadhaar identity checks send the selected challenge and accept inconclusive binding', async () => {
  const pending = client.verifyAadhaarFull({ document, backDocument: null, frames: [document, document, document],
    consentSubject: 'test-subject', challenge: 'head_turn' });
  assert.equal(lastRequest.form.get('challenge'), 'head_turn');
  lastRequest.finish(JSON.stringify({ ...valid, identity_binding: 'CHECK_FAILED' }));
  assert.equal((await pending).identity_binding, 'CHECK_FAILED');
});

test('metadata rejects invalid JSON and preserves HTTP errors', async () => {
  globalThis.fetch = async () => new Response('<html>fallback</html>');
  await assert.rejects(client.getHealth(), error => error.status === 502);
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Temporarily unavailable' }), { status: 503 });
  await assert.rejects(client.getHealth(), error => error.status === 503 && error.detail === 'Temporarily unavailable');
});

test('metadata body-read failures become recoverable API errors', async () => {
  globalThis.fetch = async () => ({ ok: true, text: async () => { throw new TypeError('connection reset'); } });
  await assert.rejects(client.getHealth(), error => error instanceof client.ApiError && error.status === 0);
});

test('malformed metadata is rejected before rendering dashboard components', async () => {
  for (const load of [client.getHealth, client.getReasons, client.getHistory, client.getSummary]) {
    globalThis.fetch = async () => new Response('{}');
    await assert.rejects(load(), error => error.status === 502);
  }
  globalThis.fetch = async () => new Response(JSON.stringify({ records: [{ verdict: 'UNKNOWN' }], disclaimer: 'test' }));
  await assert.rejects(client.getHistory(), error => error.status === 502);
  globalThis.fetch = async () => new Response(JSON.stringify({ records: [], disclaimer: 'test' }));
  assert.deepEqual((await client.getHistory()).records, []);
});
