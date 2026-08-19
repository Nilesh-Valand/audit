import { FileSearch, FileText, History, ListChecks } from "lucide-react";
import { Link } from "react-router-dom";
import { BackendUnreachable } from "./BackendUnreachable";
import { NoAuditSelected } from "./NoAuditSelected";
import { ReactNode } from "react";

export function PageShell({
  title,
  subtitle,
  actions,
  crawlRunId,
  ready,
  loading,
  error,
  unreachable,
  children,
  wide = true,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  crawlRunId: number | null;
  ready: boolean;
  loading?: boolean;
  error: string | null;
  unreachable: boolean;
  children?: ReactNode;
  wide?: boolean;
}) {
  if (!ready) {
    return (
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <span className="h-4 w-4 animate-pulse rounded-full bg-slate-200" />
        Loading workspace…
      </div>
    );
  }

  return (
    <div className={`space-y-6 ${wide ? "mx-auto max-w-7xl" : "mx-auto max-w-3xl"}`}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900 lg:text-[1.75rem]">
            {title}
          </h1>
          {subtitle ? <div className="mt-1.5 text-sm leading-relaxed text-slate-500">{subtitle}</div> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>

      {!crawlRunId ? <NoAuditSelected /> : null}
      {unreachable && error ? <BackendUnreachable message={error} /> : null}
      {!unreachable && error ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-800">
          <p>{error}</p>
          {/settings/i.test(error) ? (
            <Link to="/settings" className="mt-3 inline-block font-semibold text-brand-700 hover:underline">
              Open Settings →
            </Link>
          ) : null}
        </div>
      ) : null}
      {loading ? (
        <div className="flex items-center gap-3 text-sm text-slate-500">
          <span className="h-4 w-4 animate-pulse rounded-full bg-slate-200" />
          Loading…
        </div>
      ) : null}
      {crawlRunId && !unreachable ? children : null}
    </div>
  );
}

export function PaginationBar({
  page,
  pageSize,
  total,
  onPageChange,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-6 py-3 text-sm text-slate-600">
      <span>
        Showing {from}–{to} of {total}
      </span>
      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
          className="rounded-xl border border-slate-200 bg-white px-3 py-1.5 font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-40"
        >
          Previous
        </button>
        <span className="tabular-nums text-slate-500">
          Page {page} / {totalPages}
        </span>
        <button
          type="button"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
          className="rounded-xl border border-slate-200 bg-white px-3 py-1.5 font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </div>
  );
}

export function SeverityBadge({ severity }: { severity: string }) {
  const key = severity.toLowerCase();
  const className =
    key === "critical"
      ? "bg-red-50 text-red-700 ring-red-100"
      : key === "high"
        ? "bg-orange-50 text-orange-700 ring-orange-100"
        : key === "medium"
          ? "bg-amber-50 text-amber-700 ring-amber-100"
          : "bg-sky-50 text-sky-700 ring-sky-100";

  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize ring-1 ring-inset ${className}`}
    >
      {severity}
    </span>
  );
}

export function scoreColor(score: number | null | undefined): string {
  if (score === null || score === undefined) return "#94a3b8";
  if (score >= 95) return "#059669";
  if (score >= 85) return "#0d9488";
  if (score >= 75) return "#0284c7";
  if (score >= 60) return "#2563eb";
  if (score >= 45) return "#d97706";
  if (score >= 30) return "#ea580c";
  return "#dc2626";
}

/** Spread colors across a set of scores so close high values still look different. */
export function relativeScoreColor(score: number, minScore: number, maxScore: number): string {
  const span = Math.max(maxScore - minScore, 1);
  const t = Math.max(0, Math.min(1, (score - minScore) / span));
  // Warm (focus) → cool (healthy)
  const stops = [
    { t: 0, color: [220, 38, 38] }, // red
    { t: 0.25, color: [234, 88, 12] }, // orange
    { t: 0.5, color: [217, 119, 6] }, // amber
    { t: 0.75, color: [2, 132, 199] }, // sky
    { t: 1, color: [5, 150, 105] }, // emerald
  ];
  for (let i = 0; i < stops.length - 1; i++) {
    const a = stops[i];
    const b = stops[i + 1];
    if (t >= a.t && t <= b.t) {
      const local = (t - a.t) / (b.t - a.t || 1);
      const r = Math.round(a.color[0] + (b.color[0] - a.color[0]) * local);
      const g = Math.round(a.color[1] + (b.color[1] - a.color[1]) * local);
      const bl = Math.round(a.color[2] + (b.color[2] - a.color[2]) * local);
      return `rgb(${r}, ${g}, ${bl})`;
    }
  }
  return "rgb(5, 150, 105)";
}

export function labelCategory(category: string): string {
  if (category === "ai_readiness") return "AI Readiness";
  return category.replace(/_/g, " ");
}

export const ISSUE_CATEGORIES = [
  "technical",
  "on_page",
  "content",
  "performance",
  "structured_data",
  "security",
  "indexing",
  "crawlability",
  "ai_readiness",
] as const;

export const SEVERITIES = ["critical", "high", "medium", "low"] as const;

function ContextLink({
  to,
  icon: Icon,
  children,
}: {
  to: string;
  icon: typeof ListChecks;
  children: ReactNode;
}) {
  return (
    <Link
      to={to}
      className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm transition hover:border-slate-300 hover:bg-slate-50"
    >
      <Icon className="h-4 w-4 text-slate-400" strokeWidth={2} />
      {children}
    </Link>
  );
}

export function RunContextLinks({ projectId }: { projectId: number | null }) {
  return (
    <>
      <ContextLink to="/issues" icon={ListChecks}>
        Issues
      </ContextLink>
      <ContextLink to="/pages" icon={FileSearch}>
        Pages
      </ContextLink>
      <ContextLink to="/report" icon={FileText}>
        Report
      </ContextLink>
      {projectId ? (
        <ContextLink to={`/projects/${projectId}`} icon={History}>
          History
        </ContextLink>
      ) : null}
    </>
  );
}
