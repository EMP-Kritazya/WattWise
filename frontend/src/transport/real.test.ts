import { afterEach, expect, it, vi } from "vitest";
import { realTransport } from "./real";

afterEach(() => vi.unstubAllGlobals());

it("keeps health available while removing owner escalation resolution", async () => {
  const health = { status: "ok", engine: "ready" };
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(health)));
  vi.stubGlobal("fetch", fetchMock);
  expect(await realTransport.health()).toEqual(health);
  expect(fetchMock).toHaveBeenCalledWith("/api/health", { method: "GET", headers: undefined, body: undefined });
  expect(realTransport).not.toHaveProperty("resolveEscalation");
});
