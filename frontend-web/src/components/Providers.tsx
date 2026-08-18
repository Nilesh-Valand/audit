"use client";

import { AuditSelectionProvider } from "@/lib/AuditSelectionContext";

export function Providers({ children }: { children: React.ReactNode }) {
  return <AuditSelectionProvider>{children}</AuditSelectionProvider>;
}
