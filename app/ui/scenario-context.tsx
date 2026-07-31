"use client";

import { createContext, useContext, useMemo, useState } from "react";
import type { Scenario } from "./data";

type ScenarioState = { scenario: Scenario; setScenario: (scenario: Scenario) => void; reset: () => void };
const Context = createContext<ScenarioState | null>(null);

export function ScenarioProvider({ children }: { children: React.ReactNode }) {
  const [scenario, setScenarioState] = useState<Scenario>(() => {
    if (typeof window === "undefined") return "Busy Saturday";
    return (localStorage.getItem("fitos-scenario") as Scenario | null) ?? "Busy Saturday";
  });
  const value = useMemo(() => ({ scenario, setScenario: (next: Scenario) => { setScenarioState(next); localStorage.setItem("fitos-scenario", next); }, reset: () => { setScenarioState("Busy Saturday"); localStorage.removeItem("fitos-scenario"); } }), [scenario]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useScenario() {
  const context = useContext(Context);
  if (!context) throw new Error("useScenario must be used within ScenarioProvider");
  return context;
}
