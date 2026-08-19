import { Link } from "react-router-dom";
import { FolderKanban, PlusCircle } from "lucide-react";
import { Card, CardContent } from "./ui";

export function NoAuditSelected() {
  return (
    <Card>
      <CardContent className="py-12 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-sky-50 text-sky-600 ring-1 ring-inset ring-sky-100">
          <FolderKanban className="h-5 w-5" />
        </div>
        <h2 className="mt-4 text-base font-semibold text-slate-900">No audit selected</h2>
        <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-slate-500">
          Pick a crawl run from Projects, or start a new site audit to populate this dashboard.
        </p>
        <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
          <Link
            to="/audits/new"
            className="inline-flex items-center gap-2 rounded-xl bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-brand-700"
          >
            <PlusCircle className="h-4 w-4" />
            New Audit
          </Link>
          <Link
            to="/projects"
            className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50"
          >
            <FolderKanban className="h-4 w-4 text-slate-400" />
            Projects
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}
