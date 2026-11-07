import {useEffect, useState, type ReactNode} from 'react';
import {request} from '../lib/http-client';
import {setNovelResources, validateNovelResources} from '../lib/novel-resources';

export default function NovelResourceGate({children}: {children: ReactNode}) {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setReady(false); setError('');
    setNovelResources({});
    request<{workflows: Record<string, string>;new_book_defaults?:Parameters<typeof setNovelResources>[1]}>('/novel-console/resources').then(result => {
      if (active) {
        validateNovelResources(result?.workflows);
        setNovelResources(result.workflows,result.new_book_defaults); setReady(true);
      }
    }).catch(reason => {if (active) setError(String(reason));});
    return () => {active = false;};
  }, [attempt]);
  if (!ready) return <div className="p-8 space-y-4" role="status">
    <p>{error || '正在加载小说插件…'}</p>
    {error && <button className="rounded border p-2" onClick={() => setAttempt(n => n + 1)}>重新检查插件</button>}
  </div>;
  return children;
}
