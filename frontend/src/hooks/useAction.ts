import { useCallback, useState } from "react";
import { errorMessage } from "@/lib/utils";

/** Run a server call from a button: tracks busy state and keeps the error message to show next to it. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }, []);
  return { run, busy, error };
}
