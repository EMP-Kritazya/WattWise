import { mockTransport } from "@/mocks/server";
import { realTransport } from "./real";
import type { Transport } from "./types";

export type { ConnectionStatus, Transport } from "./types";
export { ApiError } from "./errors";

let fixturePromise: Promise<Transport> | undefined;
const loadFixture = () => (fixturePromise ??= import("@/mocks/rest").then((module) => module.fixtureTransport));

/** Keeps the large JSONL fixture streams out of the production entry chunk. */
const lazyFixtureTransport: Transport = {
  kind: "mock",
  getCatalog: () => loadFixture().then((transport) => transport.getCatalog()),
  createKitchen: (body) => loadFixture().then((transport) => transport.createKitchen(body)),
  getKitchen: () => loadFixture().then((transport) => transport.getKitchen()),
  setImportance: (deviceId, body) => loadFixture().then((transport) => transport.setImportance(deviceId, body)),
  setPeakCap: (body) => loadFixture().then((transport) => transport.setPeakCap(body)),
  simControl: (body) => loadFixture().then((transport) => transport.simControl(body)),
  deviceCommand: (deviceId, body) => loadFixture().then((transport) => transport.deviceCommand(deviceId, body)),
  addCustomers: (body) => loadFixture().then((transport) => transport.addCustomers(body)),
  undo: (decisionId) => loadFixture().then((transport) => transport.undo(decisionId)),
  listDecisions: (limit) => loadFixture().then((transport) => transport.listDecisions(limit)),
  runBacktest: (body) => loadFixture().then((transport) => transport.runBacktest(body)),
  getBacktest: (runId) => loadFixture().then((transport) => transport.getBacktest(runId)),
  chat: (message) => loadFixture().then((transport) => transport.chat(message)),
  listProposals: (status) => loadFixture().then((transport) => transport.listProposals(status)),
  confirmProposal: (proposalId, confirm) => loadFixture().then((transport) => transport.confirmProposal(proposalId, confirm)),
  setAuthority: (body) => loadFixture().then((transport) => transport.setAuthority(body)),
  setPreferences: (text) => loadFixture().then((transport) => transport.setPreferences(text)),
  getContext: () => loadFixture().then((transport) => transport.getContext()),
  listEscalations: (status) => loadFixture().then((transport) => transport.listEscalations(status)),
  resolveEscalation: (escalationId, optionId) =>
    loadFixture().then((transport) => transport.resolveEscalation(escalationId, optionId)),
  health: () => loadFixture().then((transport) => transport.health()),
  subscribe(onMessage, onStatus) {
    let stopped = false;
    let unsubscribe: (() => void) | undefined;
    void loadFixture().then((transport) => {
      if (!stopped) unsubscribe = transport.subscribe(onMessage, onStatus);
    });
    return () => {
      stopped = true;
      unsubscribe?.();
    };
  },
};

/** Fixture mode is the contract source of truth; the old hand-written mock remains available only during screen migration. */
export const transport: Transport =
  import.meta.env.VITE_MOCKS === "1" ? lazyFixtureTransport : import.meta.env.VITE_MOCK === "1" ? mockTransport : realTransport;
