import { useEffect } from "react";
import { HubLink, useHubStatus, type HubConnectionState } from "@/hub";

export const isFixtureHub = import.meta.env.VITE_MOCKS === "1" || import.meta.env.VITE_MOCK === "1";

/** Data-boundary hook for the dedicated /sim screen; screens never import the simulation or hub directly. */
export function useHubHost() {
  const status = useHubStatus();
  useEffect(() => {
    const link = new HubLink();
    if (isFixtureHub) void link.connectMock();
    else link.connect();
    return () => link.close();
  }, []);
  return status;
}

export type { HubConnectionState };
