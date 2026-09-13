import test from 'node:test';
import assert from 'node:assert/strict';
import {adminApi} from '../src/lib/api.ts';

test('unblock sends the required reason to the API', async () => {
 const original = globalThis.fetch;
 try {
  let request;
  globalThis.fetch = async (url, init) => {request={url,init};return Response.json({unblocked:true});};
  await adminApi.unblockKey('key-1', 'Reviewed traffic');
  assert.ok(request.url.endsWith('/admin/abuse/unblock/key-1'));
  assert.deepEqual(JSON.parse(request.init.body), {reason:'Reviewed traffic'});
 } finally {globalThis.fetch=original;}
});
test('successful empty responses do not become JSON parse errors', async () => {
 const original = globalThis.fetch;
 try {globalThis.fetch=async()=>new Response(null,{status:204});assert.equal(await adminApi.deleteKey('key-1'),undefined);}
 finally {globalThis.fetch=original;}
});
test('API errors reach callers', async () => {
 const original=globalThis.fetch;
 try {globalThis.fetch=async()=>Response.json({detail:'Access denied'},{status:403});await assert.rejects(adminApi.getKeys(),/Access denied/);}
 finally {globalThis.fetch=original;}
});
