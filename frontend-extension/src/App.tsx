import { HashRouter, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { AuditSelectionProvider } from "@/lib/AuditSelectionContext";
import DashboardPage from "@/pages/Dashboard";
import NewAuditPage from "@/pages/NewAudit";
import ProjectsPage from "@/pages/Projects";
import IssuesPage from "@/pages/Issues";
import PagesPage from "@/pages/Pages";
import ReportPage from "@/pages/Report";
import CurrentPageCheckPage from "@/pages/CurrentPageCheck";
import SettingsPage from "@/pages/Settings";
import NotFound from "@/pages/NotFound";

// Chrome extension pages have no server, so routing lives entirely in the
// hash fragment (chrome-extension://<id>/index.html#/pages etc.) — this
// works from a single static index.html with no server-side rewrites.
export default function App() {
  return (
    <AuditSelectionProvider>
      <HashRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/audits/new" element={<NewAuditPage />} />
            <Route path="/projects" element={<ProjectsPage />} />
            <Route path="/projects/:projectId" element={<ProjectsPage />} />
            <Route path="/issues" element={<IssuesPage />} />
            <Route path="/pages" element={<PagesPage />} />
            <Route path="/report" element={<ReportPage />} />
            <Route path="/current-page" element={<CurrentPageCheckPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </HashRouter>
    </AuditSelectionProvider>
  );
}
