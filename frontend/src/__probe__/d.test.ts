import { test } from "vitest";
import { writeFileSync } from "node:fs";
import { HubLink } from "@/hub/link";
test("day", async () => {
  const viewer = new WebSocket("ws://localhost:8001/ws");
  const s: number[] = []; let decisions = 0; let last: any = null;
  viewer.onmessage = (e) => { const m = JSON.parse(String(e.data));
    if (m.type === "comparison") { last = m.data; s.push(m.data.saved_month_usd); }
    if (m.type === "decision") decisions++; };
  const link = new HubLink(); link.connect("ws://localhost:8001/ws/hub");
  await new Promise((r) => setTimeout(r, 3000));
  await fetch("http://localhost:8001/api/sim/control", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action: "play", speed: 600 }) });
  const surgeAt = (process.env.SURGES ?? "").split(",").filter(Boolean).map(Number);
  let waited = 0;
  for (const t of surgeAt) { await new Promise((r) => setTimeout(r, (t - waited) * 1000)); waited = t;
    await fetch("http://localhost:8001/api/events/customers", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ customers: 40, duration_min: 60 }) }); }
  await new Promise((r) => setTimeout(r, (40 - waited) * 1000));
  link.close(); viewer.close();
  writeFileSync(process.env.DOUT!, JSON.stringify({ decisions, n: s.length, min: Math.min(...s), max: Math.max(...s), last }));
}, 60000);
