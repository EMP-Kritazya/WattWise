import type {
  BacktestResult,
  BacktestRunRequest,
  ClaudeAuthority,
  ClockState,
  Context,
  Escalation,
  Health,
  Proposal,
  Command,
  CustomerEventRequest,
  Decision,
  Device,
  DeviceCommandRequest,
  EquipmentType,
  ImportanceUpdate,
  KitchenConfig,
  KitchenView,
  Meter,
  PeakCapUpdate,
  SimControlRequest,
  WsMessage,
} from "@/types";

export type ConnectionStatus = "connecting" | "open" | "closed";

/**
 * Everything the UI can ask of the server: one method per REST endpoint in CONTRACTS.md section 2,
 * plus the /ws message stream. Implemented by the real server client and by src/mocks.
 */
export interface Transport {
  readonly kind: "real" | "mock";

  getCatalog(): Promise<EquipmentType[]>;
  createKitchen(config: KitchenConfig): Promise<{ kitchen_id: string }>;
  getKitchen(): Promise<KitchenView>;
  setImportance(deviceId: string, body: ImportanceUpdate): Promise<Device>;
  setPeakCap(body: PeakCapUpdate): Promise<Meter>;
  simControl(body: SimControlRequest): Promise<ClockState>;
  deviceCommand(deviceId: string, body: DeviceCommandRequest): Promise<Command>;
  addCustomers(body: CustomerEventRequest): Promise<void>;
  undo(decisionId: string): Promise<Decision>;
  listDecisions(limit?: number): Promise<Decision[]>;
  runBacktest(body: BacktestRunRequest): Promise<{ run_id: string }>;
  getBacktest(runId: string): Promise<BacktestResult[]>;
  chat(message: string): Promise<{ chat_id: string }>;
  listProposals(status?: Proposal["status"]): Promise<Proposal[]>;
  confirmProposal(proposalId: string, confirm: boolean): Promise<Proposal>;
  setAuthority(authority: ClaudeAuthority): Promise<void>;
  setPreferences(text: string): Promise<void>;
  getContext(): Promise<Context>;
  listEscalations(status?: Escalation["status"]): Promise<Escalation[]>;
  /** Owner's choice from the UI; the engine validates it. */
  resolveEscalation(escalationId: string, optionId: string): Promise<Escalation>;
  health(): Promise<Health>;

  /** Listen to /ws. Returns an unsubscribe function. */
  subscribe(onMessage: (msg: WsMessage) => void, onStatus: (status: ConnectionStatus) => void): () => void;
}
