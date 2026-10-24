import { mockTransport } from "@/mocks/server";
import { realTransport } from "./real";
import type { Transport } from "./types";

export type { ConnectionStatus, Transport } from "./types";
export { ApiError } from "./errors";

/** `npm run dev:mock` (VITE_MOCK=1) uses the in-browser fake server; otherwise the FastAPI server. */
export const transport: Transport = import.meta.env.VITE_MOCK === "1" ? mockTransport : realTransport;
