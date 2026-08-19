import { Outlet } from "react-router-dom";
import { Sidebar } from "@/components/Sidebar";

export function AppShell() {
  return (
    <div className="flex min-h-screen bg-slate-50">
      <Sidebar />
      <main className="min-h-screen flex-1 overflow-y-auto">
        <div className="mx-auto min-h-screen px-6 py-6 lg:px-8 lg:py-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
