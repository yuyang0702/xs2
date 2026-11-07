import test from 'node:test';
import assert from 'node:assert/strict';
import {controlAutomation} from './novel-automation';

test('start reconciles an identical autosave revision without losing author intent', async t => {
  const state={_revision:1,title:'Test',values:{human_intent:'保留人物选择'},autoNext:true,autoArmed:true};
  const calls:Array<{url:string;state?:typeof state}>=[];
  t.mock.method(globalThis,'fetch',async(url:string,options?:RequestInit)=>{
    calls.push({url:String(url),state:options?.body?JSON.parse(String(options.body)).state:undefined});
    if(calls.length===1) return new Response(JSON.stringify({detail:'作品已在后台更新'}),{status:409});
    if(calls.length===2) return new Response(JSON.stringify({state:{...state,_revision:2,autoArmed:false,automaticRecovery:{}}}));
    return new Response(JSON.stringify({state:{...state,_revision:3},revision:3,workspace:'book'}));
  });
  const result=await controlAutomation('start','build','book',state);
  assert.equal(result.revision,3);
  assert.equal(calls.length,3);
  assert.equal(calls[2].state?._revision,2);
  assert.deepEqual(calls[2].state?.values,{human_intent:'保留人物选择'});
});

test('start never rebases over another author edit or an already armed project',async t=>{
  for(const changed of [{values:{human_intent:'另一窗口的新意见'}},{autoController:'server-v1',autoArmed:true,autoNext:true}]){
    let posts=0;
    t.mock.method(globalThis,'fetch',async(_url:string,options?:RequestInit)=>{
      if(options?.method==='POST'){posts++;return new Response('{}',{status:409});}
      return new Response(JSON.stringify({state:{title:'Test',values:{human_intent:'旧意见'},_revision:2,...changed}}));
    });
    await assert.rejects(controlAutomation('start','build','book',{title:'Test',values:{human_intent:'旧意见'},_revision:1}));
    assert.equal(posts,1);
    t.mock.restoreAll();
  }
});
