import assert from 'node:assert/strict';
import test from 'node:test';
import {api} from '../lib/api.ts';

test('history filters receive every cursor page, including validated runs', async (t) => {
  const calls=[];
  t.mock.method(globalThis,'fetch',async (url)=>{
    calls.push(String(url));
    const before=new URL(url).searchParams.get('before_id');
    const rows=before ? [{id:5},{id:4}] : Array.from({length:200},(_,i)=>({id:205-i}));
    return new Response(JSON.stringify(rows),{status:200});
  });
  const evaluations=await api.evaluations();
  assert.equal(evaluations.length,202);
  assert.match(calls[1],/before_id=6/);
  assert.equal(new Set(evaluations.map(row=>row.id)).size,202);
  calls.length=0;
  const runs=await api.runs(true);
  assert.equal(runs.length,202);
  assert.ok(calls.every(url=>url.includes('validated_only=true')));
});

test('a later history-page failure does not return a misleading partial history',async (t)=>{
  t.mock.method(globalThis,'fetch',async (url)=>new URL(url).searchParams.has('before_id')
    ? new Response(JSON.stringify({detail:'failed page'}),{status:500})
    : new Response(JSON.stringify(Array.from({length:200},(_,i)=>({id:205-i})))));
  await assert.rejects(api.evaluations(),/failed page/);
});
