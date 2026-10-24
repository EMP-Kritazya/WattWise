import chatDeltaFixture from "@fixtures/ws/chat_delta.json";
import chatDoneFixture from "@fixtures/ws/chat_done.json";
import { ApiError } from "@/transport/errors";
import type { Transport } from "@/transport/types";
import type { WsMessage } from "@/types";
import { restFixtures, type RestFixture } from "./fixtures";
import { broadcastFixtureMessage, subscribeFixtureViewer } from "./viewerWs";

const clone = <T,>(value: T): T => structuredClone(value);
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

const dynamicFallback = (method: string, path: string): string | null => {
  if (method === "GET" && /^\/api\/backtest\/[^/]+$/.test(path)) return "/api/backtest/run_0001";
  if (method === "PUT" && /^\/api\/kitchen\/devices\/[^/]+\/importance$/.test(path)) return "/api/kitchen/devices/walk_in_cooler_1/importance";
  if (method === "POST" && /^\/api\/devices\/[^/]+\/command$/.test(path)) return "/api/devices/ice_machine_1/command";
  if (method === "POST" && /^\/api\/decisions\/[^/]+\/undo$/.test(path)) return "/api/decisions/d_0001/undo";
  if (method === "POST" && /^\/api\/proposals\/[^/]+\/confirm$/.test(path)) return "/api/proposals/p_0001/confirm";
  if (method === "POST" && /^\/api\/escalations\/[^/]+\/resolve$/.test(path)) return "/api/escalations/e_0001/resolve";
  return null;
};

function candidates(method: string, path: string): RestFixture[] {
  const direct = restFixtures.filter((fixture) => fixture.method === method && fixture.path === path);
  if (direct.length) return direct;
  const fallback = dynamicFallback(method, path);
  return fallback ? restFixtures.filter((fixture) => fixture.method === method && fixture.path === fallback) : [];
}

/** Fixture router: exact error examples win only when their request body also matches. */
export async function fixtureRequest<T>(method: string, path: string, body?: unknown): Promise<T> {
  const matches = candidates(method, path);
  const exactError = matches.find((fixture) => fixture.status >= 400 && same(fixture.request, body ?? null));
  const fixture = exactError ?? matches.find((item) => item.status >= 200 && item.status < 300);
  if (!fixture) throw new ApiError(404, `No REST fixture for ${method} ${path}`);
  if (fixture.status >= 400) {
    const response = fixture.response as { detail?: string };
    throw new ApiError(fixture.status, response.detail ?? `${method} ${path} failed (${fixture.status})`);
  }
  return clone(fixture.response) as T;
}

const enc = encodeURIComponent;

/** Transport used by VITE_MOCKS=1. Every response and viewer message comes from contracts/fixtures. */
export const fixtureTransport: Transport = {
  kind: "mock",
  getCatalog: () => fixtureRequest("GET", "/api/catalog"),
  createKitchen: (body) => fixtureRequest("POST", "/api/kitchen", body),
  getKitchen: () => fixtureRequest("GET", "/api/kitchen"),
  setImportance: (deviceId, body) => fixtureRequest("PUT", `/api/kitchen/devices/${enc(deviceId)}/importance`, body),
  setPeakCap: (body) => fixtureRequest("PUT", "/api/kitchen/peak-cap", body),
  simControl: (body) => fixtureRequest("POST", "/api/sim/control", body),
  deviceCommand: (deviceId, body) => fixtureRequest("POST", `/api/devices/${enc(deviceId)}/command`, body),
  async addCustomers(body) {
    await fixtureRequest("POST", "/api/events/customers", body);
  },
  undo: (decisionId) => fixtureRequest("POST", `/api/decisions/${enc(decisionId)}/undo`),
  listDecisions: (limit = 50) => fixtureRequest("GET", `/api/decisions?limit=${limit}`),
  runBacktest: (body) => fixtureRequest("POST", "/api/backtest/run", body),
  getBacktest: (runId) => fixtureRequest("GET", `/api/backtest/${enc(runId)}`),
  async chat(message) {
    const response = await fixtureRequest<{ chat_id: string }>("POST", "/api/chat", { message });
    setTimeout(() => broadcastFixtureMessage(clone(chatDeltaFixture) as WsMessage), 40);
    setTimeout(() => broadcastFixtureMessage(clone(chatDoneFixture) as WsMessage), 80);
    return response;
  },
  listProposals: (status = "pending") => fixtureRequest("GET", `/api/proposals?status=${status}`),
  confirmProposal: (proposalId, confirm) => fixtureRequest("POST", `/api/proposals/${enc(proposalId)}/confirm`, { confirm }),
  async setAuthority(body) {
    await fixtureRequest("PUT", "/api/kitchen/authority", body);
  },
  async setPreferences(text) {
    await fixtureRequest("PUT", "/api/kitchen/preferences", { text });
  },
  getContext: () => fixtureRequest("GET", "/api/context"),
  listEscalations: (status = "open") => fixtureRequest("GET", `/api/escalations?status=${status}`),
  resolveEscalation: (escalationId, optionId) =>
    fixtureRequest("POST", `/api/escalations/${enc(escalationId)}/resolve`, { option_id: optionId }),
  health: () => fixtureRequest("GET", "/api/health"),
  subscribe: subscribeFixtureViewer,
};
