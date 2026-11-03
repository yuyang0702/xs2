import { useEffect, useRef, useState } from "react";

/** Serialize author actions and invalidate results on an unmounted scope. */
export function useAction() {
  const inFlight = useRef<AbortController | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => () => inFlight.current?.abort(), []);
  async function run(action: (signal: AbortSignal) => Promise<void>) {
    if (inFlight.current) return;
    const controller = new AbortController();
    inFlight.current = controller;
    setBusy(true);
    try { await action(controller.signal); }
    finally {
      inFlight.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return { busy, run };
}
