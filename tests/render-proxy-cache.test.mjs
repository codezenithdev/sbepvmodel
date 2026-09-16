import assert from 'node:assert/strict';
import test from 'node:test';
import {proxyRenderRequest} from '../lib/render-proxy.ts';

function mock(t, fetch) {
  const originalFetch = globalThis.fetch;
  const keys = ['RENDER_BASIC_USER', 'RENDER_BASIC_PASSWORD', 'RENDER_BACKEND_ORIGIN'];
  const previous = keys.map(key => process.env[key]);
  [process.env.RENDER_BASIC_USER, process.env.RENDER_BASIC_PASSWORD, process.env.RENDER_BACKEND_ORIGIN] = ['cache-test', 'fixture-password', 'https://backend.invalid'];
  globalThis.fetch = fetch;
  t.after(() => {
    globalThis.fetch = originalFetch;
    keys.forEach((key, i) => previous[i] === undefined ? delete process.env[key] : process.env[key] = previous[i]);
  });
}
const proxy = (prefix, path, init = {}) => proxyRenderRequest(
  new Request(`https://dashboard.invalid/${prefix}/${path.join('/')}`, init),
  {params: Promise.resolve({path})}, prefix,
);

test('conditional output requests preserve validators, Vary and 304', async t => {
  const modified = 'Wed, 16 Sep 2026 00:00:00 GMT';
  mock(t, async (_url, init) => {
    assert.equal(init.headers.get('if-none-match'), '"v1"');
    assert.equal(init.headers.get('if-modified-since'), modified);
    return new Response(null, {status: 304, headers: {ETag: '"v1"', 'Last-Modified': modified, Vary: 'Origin, Accept-Encoding', 'Cache-Control': 'private, max-age=0, must-revalidate'}});
  });
  const response = await proxy('outputs', ['fixture.png'], {headers: {'If-None-Match': '"v1"', 'If-Modified-Since': modified}});
  assert.equal(response.status, 304);
  assert.equal(await response.text(), '');
  assert.equal(response.headers.get('etag'), '"v1"');
  assert.equal(response.headers.get('last-modified'), modified);
  assert.equal(response.headers.get('vary'), 'Origin, Accept-Encoding');
  assert.equal(response.headers.get('cache-control'), 'private, max-age=0, must-revalidate');
});

test('range requests retain If-Range and partial response metadata', async t => {
  mock(t, async (_url, init) => {
    assert.equal(init.headers.get('range'), 'bytes=0-2');
    assert.equal(init.headers.get('if-range'), '"v1"');
    return new Response('abc', {status: 206, headers: {'Accept-Ranges': 'bytes', 'Content-Range': 'bytes 0-2/6', 'Content-Length': '3'}});
  });
  const response = await proxy('outputs', ['fixture.csv'], {headers: {Range: 'bytes=0-2', 'If-Range': '"v1"'}});
  assert.equal(response.status, 206);
  assert.equal(response.headers.get('content-range'), 'bytes 0-2/6');
  assert.equal(response.headers.get('accept-ranges'), 'bytes');
  assert.equal(await response.text(), 'abc');
});

test('mutable API responses forbid caching and use only service credentials', async t => {
  mock(t, async (_url, init) => {
    assert.equal(init.cache, 'no-store');
    assert.equal(init.headers.get('authorization'), `Basic ${Buffer.from('cache-test:fixture-password').toString('base64')}`);
    return Response.json({state: 'running'}, {headers: {'Cache-Control': 'public, max-age=3600', Vary: 'Origin'}});
  });
  const response = await proxy('api', ['status', 'job123'], {headers: {Authorization: 'Bearer untrusted-client'}});
  assert.equal(response.headers.get('cache-control'), 'private, no-store');
  assert.equal(response.headers.get('vary'), 'Origin');
  assert.deepEqual(await response.json(), {state: 'running'});
});

test('HEAD retains output metadata without a response body', async t => {
  mock(t, async (_url, init) => {
    assert.equal(init.method, 'HEAD');
    return new Response(null, {headers: {ETag: '"v1"', 'Content-Length': '123'}});
  });
  const response = await proxy('outputs', ['fixture.png'], {method: 'HEAD'});
  assert.equal(response.headers.get('etag'), '"v1"');
  assert.equal(response.headers.get('content-length'), '123');
  assert.equal(await response.text(), '');
});

test('network and credential errors are not cacheable', async t => {
  mock(t, async () => {throw new Error('Fixture unavailable');});
  const unavailable = await proxy('api', ['session']);
  assert.equal(unavailable.status, 502);
  assert.equal(unavailable.headers.get('cache-control'), 'private, no-store');
  delete process.env.RENDER_BASIC_PASSWORD;
  const missing = await proxy('api', ['session']);
  assert.equal(missing.status, 503);
  assert.equal(missing.headers.get('cache-control'), 'private, no-store');
});

test('retired routes stay blocked without contacting the backend', async t => {
  let calls = 0;
  mock(t, async () => {calls++; return new Response('unexpected');});
  const response = await proxy('api', ['autonomy', 'cases']);
  assert.equal(response.status, 404);
  assert.equal(calls, 0);
  assert.equal(response.headers.get('cache-control'), 'private, no-store');
});
