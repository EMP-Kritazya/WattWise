import { useEffect, useState } from "react";
import type { EvalArtifact } from "@/types";

type EvalState = { kind: "loading" } | { kind: "ready"; artifact: EvalArtifact } | { kind: "error"; message: string };

/**
 * The Evaluation Lab's only data door: one precomputed eval artifact (docs/Claude_EVAL.md §11).
 * STUB: no eval artifact or endpoint exists yet, so every mode loads the illustrative placeholder.
 * When the eval runner publishes artifacts, swap the import for that file or a PROPOSED endpoint; screens don't change.
 */
export function useEvalArtifact(): EvalState {
  const [state, setState] = useState<EvalState>({ kind: "loading" });

  useEffect(() => {
    let live = true;
    import("@/mocks/evalStub")
      .then(({ EVAL_STUB }) => live && setState({ kind: "ready", artifact: EVAL_STUB }))
      .catch((error: unknown) => live && setState({ kind: "error", message: error instanceof Error ? error.message : "Eval artifact failed to load" }));
    return () => {
      live = false;
    };
  }, []);

  return state;
}
