import { transport } from "@/transport";

/** REST facade matching CONTRACTS.md section 2. Screens never select a concrete transport. */
export const useApi = () => transport;
export const api = transport;
