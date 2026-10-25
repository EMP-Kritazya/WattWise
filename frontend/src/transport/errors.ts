/** A failed REST call. `message` is the server's reason (FastAPI `detail`, e.g. the engine's RuleError on 422). */
export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
