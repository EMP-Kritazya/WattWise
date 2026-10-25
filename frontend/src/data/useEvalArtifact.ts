import type { EvalArtifact } from "@/types";

type EvalState =
  | { kind: "loading" }
  | { kind: "ready"; artifact: EvalArtifact }
  | { kind: "error"; message: string }
  | { kind: "empty" };

/**
 * The Evaluation Lab's only data door: one precomputed eval artifact (docs/Claude_EVAL.md §11).
 * No eval runner or endpoint exists yet, so there is nothing real to show: "empty", never placeholder results
 * (the illustrative stub was removed on Oct 25, "don't use fake data"). When the runner publishes artifacts, load the
 * artifact here and return "ready"; the screen does not change.
 */
export function useEvalArtifact(): EvalState {
  return { kind: "empty" };
}
