import { Sidebar } from "@/components/Sidebar";

/**
 * App chrome mirrored from extension/src/App.tsx
 * (Sidebar + padded main). Route outlet → {children}.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen bg-slate-50">
      <Sidebar />
      <main className="min-h-screen flex-1 overflow-y-auto">
        <div className="mx-auto min-h-screen px-6 py-6 lg:px-8 lg:py-8">{children}</div>
      </main>
    </div>
  );
}
