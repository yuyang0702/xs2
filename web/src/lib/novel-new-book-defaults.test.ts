import test from 'node:test';
import assert from 'node:assert/strict';
import {setNovelResources,novelNewBookDefaults} from './novel-resources';

test('plugin defaults apply only to fresh books and cannot mutate another draft',()=>{
  const defaults={analysisModel:'sys:analysis',writerModel:'ark:writer',polishModel:'flare:polisher',values:{writer_type:'muti'}};
  setNovelResources({build:'build'},defaults);
  assert.deepEqual(novelNewBookDefaults(false),{});
  const first=novelNewBookDefaults();
  assert.deepEqual(first,defaults);
  first.values!.writer_type='single';
  assert.equal(novelNewBookDefaults().values?.writer_type,'muti');
  setNovelResources({});
  assert.deepEqual(novelNewBookDefaults(),{});
});
