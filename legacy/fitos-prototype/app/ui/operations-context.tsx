"use client";
import { createContext, useContext, useState } from "react";
const OperationsContext = createContext<{ lastUpdate: string; record: (message: string) => void } | null>(null);
export function OperationsProvider({ children }: { children: React.ReactNode }) { const [lastUpdate, setLastUpdate] = useState("No recent room update"); return <OperationsContext.Provider value={{ lastUpdate, record: setLastUpdate }}>{children}</OperationsContext.Provider>; }
export function useOperations() { const context = useContext(OperationsContext); if (!context) throw new Error("useOperations must be used within OperationsProvider"); return context; }
