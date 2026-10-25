import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import catalogFixture from "@fixtures/rest/get_catalog.json";
import kitchenFixture from "@fixtures/rest/get_kitchen.json";
import { useDashboardStore } from "@/data";
import type { EquipmentType, KitchenView } from "@/types";
import { Showcase } from "./Showcase";
import "./showcase.css";

// The 3D floor reads the kitchen layout and the catalog from the store; the showcase loads the Demo Café fixture once.
const store = useDashboardStore.getState();
store.setCatalog(catalogFixture.response as unknown as EquipmentType[]);
store.setKitchen(kitchenFixture.response as unknown as KitchenView);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Showcase />
  </StrictMode>,
);
