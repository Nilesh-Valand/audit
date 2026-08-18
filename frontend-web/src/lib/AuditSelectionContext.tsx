"use client";

import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { clearSelectedAudit, getSelectedAudit, setSelectedAudit } from "./storage";

type AuditSelectionContextValue = {
  projectId: number | null;
  crawlRunId: number | null;
  ready: boolean;
  selectAudit: (projectId: number, crawlRunId: number) => Promise<void>;
  clearSelection: () => Promise<void>;
  clearRunIfMatching: (crawlRunId: number) => Promise<void>;
  clearProjectIfMatching: (projectId: number) => Promise<void>;
};

const AuditSelectionContext = createContext<AuditSelectionContextValue | null>(null);

export function AuditSelectionProvider({ children }: { children: ReactNode }) {
  const [projectId, setProjectId] = useState<number | null>(null);
  const [crawlRunId, setCrawlRunId] = useState<number | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    void getSelectedAudit().then((selected) => {
      setProjectId(selected.projectId);
      setCrawlRunId(selected.crawlRunId);
      setReady(true);
    });
  }, []);

  const selectAudit = useCallback(async (nextProjectId: number, nextCrawlRunId: number) => {
    setProjectId(nextProjectId);
    setCrawlRunId(nextCrawlRunId);
    await setSelectedAudit({ projectId: nextProjectId, crawlRunId: nextCrawlRunId });
  }, []);

  const clearSelection = useCallback(async () => {
    setProjectId(null);
    setCrawlRunId(null);
    await clearSelectedAudit();
  }, []);

  const clearRunIfMatching = useCallback(
    async (runId: number) => {
      if (crawlRunId === runId) {
        await clearSelection();
      }
    },
    [crawlRunId, clearSelection],
  );

  const clearProjectIfMatching = useCallback(
    async (id: number) => {
      if (projectId === id) {
        await clearSelection();
      }
    },
    [projectId, clearSelection],
  );

  const value = useMemo(
    () => ({
      projectId,
      crawlRunId,
      ready,
      selectAudit,
      clearSelection,
      clearRunIfMatching,
      clearProjectIfMatching,
    }),
    [
      projectId,
      crawlRunId,
      ready,
      selectAudit,
      clearSelection,
      clearRunIfMatching,
      clearProjectIfMatching,
    ],
  );

  return <AuditSelectionContext.Provider value={value}>{children}</AuditSelectionContext.Provider>;
}

export function useAuditSelection() {
  const ctx = useContext(AuditSelectionContext);
  if (!ctx) {
    throw new Error("useAuditSelection must be used within AuditSelectionProvider");
  }
  return ctx;
}
