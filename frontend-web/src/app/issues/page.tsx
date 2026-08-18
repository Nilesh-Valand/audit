"use client";

import { useEffect, useState, type ReactNode } from "react";
import {
  ChevronDown,
  ChevronRight,
  Filter,
  ListChecks,
  RotateCcw,
  Search,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui";
import {
  ISSUE_CATEGORIES,
  labelCategory,
  PageShell,
  PaginationBar,
  SEVERITIES,
  SeverityBadge,
} from "@/components/PageShell";
import { apiClient, type AuditIssue, type PageDetails } from "@/lib/api";
import { useAuditSelection } from "@/lib/AuditSelectionContext";
import { formatBackendError, shouldLinkToSettings } from "@/lib/errors";

const PAGE_SIZE = 25;

const SEVERITY_CHIP: Record<string, string> = {
  critical: "bg-red-50 text-red-700 ring-red-200 data-[active=true]:bg-red-600 data-[active=true]:text-white data-[active=true]:ring-red-600",
  high: "bg-orange-50 text-orange-700 ring-orange-200 data-[active=true]:bg-orange-600 data-[active=true]:text-white data-[active=true]:ring-orange-600",
  medium: "bg-amber-50 text-amber-700 ring-amber-200 data-[active=true]:bg-amber-500 data-[active=true]:text-white data-[active=true]:ring-amber-500",
  low: "bg-sky-50 text-sky-700 ring-sky-200 data-[active=true]:bg-sky-600 data-[active=true]:text-white data-[active=true]:ring-sky-600",
};

export default function IssuesPage() {
  const { crawlRunId, ready } = useAuditSelection();
  const [category, setCategory] = useState("");
  const [severity, setSeverity] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<AuditIssue[]>([]);
  const [total, setTotal] = useState(0);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    setPage(1);
    setExpandedId(null);
  }, [category, severity, crawlRunId]);

  useEffect(() => {
    if (!ready || !crawlRunId) return;
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      setUnreachable(false);
      try {
        const res = await apiClient.getIssues(crawlRunId!, {
          category: category || undefined,
          severity: severity || undefined,
          page,
          page_size: PAGE_SIZE,
        });
        if (cancelled) return;
        setItems(res.items);
        setTotal(res.total);
      } catch (err) {
        if (cancelled) return;
        setUnreachable(shouldLinkToSettings(err));
        setError(formatBackendError(err));
        setItems([]);
        setTotal(0);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [ready, crawlRunId, category, severity, page]);

  const q = query.trim().toLowerCase();
  const visibleItems = q
    ? items.filter((issue) => {
        const hay = [
          issue.message,
          issue.rule_id,
          issue.category,
          issue.severity,
          issue.target_url ?? "",
        ]
          .join(" ")
          .toLowerCase();
        return hay.includes(q);
      })
    : items;

  const hasFilters = Boolean(category || severity || query.trim());

  return (
    <PageShell
      title="Issues"
      subtitle={
        crawlRunId
          ? `Prioritized findings for crawl run #${crawlRunId}`
          : "No audit selected."
      }
      crawlRunId={crawlRunId}
      ready={ready}
      loading={false}
      error={error}
      unreachable={unreachable}
    >
      <div className="space-y-4">
        {/* Filter toolbar */}
        <Card>
          <CardContent className="space-y-5 py-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-sky-50 text-sky-600 ring-1 ring-inset ring-sky-100">
                  <Filter className="h-4 w-4" />
                </span>
                <div>
                  <div className="text-sm font-semibold text-slate-900">Filter findings</div>
                  <div className="text-xs text-slate-500">
                    {loading ? "Refreshing…" : `${total} issue${total === 1 ? "" : "s"} in this run`}
                  </div>
                </div>
              </div>
              {hasFilters ? (
                <button
                  type="button"
                  onClick={() => {
                    setCategory("");
                    setSeverity("");
                    setQuery("");
                  }}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-600 shadow-sm hover:bg-slate-50"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  Reset
                </button>
              ) : null}
            </div>

            <div className="relative">
              <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search message, rule, URL…"
                className="w-full rounded-2xl border border-slate-200 bg-slate-50/80 py-2.5 pl-10 pr-4 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-sky-300 focus:bg-white focus:ring-2 focus:ring-sky-100"
              />
            </div>

            <div className="space-y-3">
              <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
                Severity
              </div>
              <div className="flex flex-wrap gap-2">
                <FilterChip
                  active={!severity}
                  onClick={() => setSeverity("")}
                  className="bg-slate-50 text-slate-600 ring-slate-200 data-[active=true]:bg-slate-900 data-[active=true]:text-white data-[active=true]:ring-slate-900"
                >
                  All
                </FilterChip>
                {SEVERITIES.map((s) => (
                  <FilterChip
                    key={s}
                    active={severity === s}
                    onClick={() => setSeverity(severity === s ? "" : s)}
                    className={SEVERITY_CHIP[s]}
                  >
                    <span className="capitalize">{s}</span>
                  </FilterChip>
                ))}
              </div>
            </div>

            <div className="space-y-3">
              <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
                Category
              </div>
              <div className="flex flex-wrap gap-2">
                <FilterChip
                  active={!category}
                  onClick={() => setCategory("")}
                  className="bg-slate-50 text-slate-600 ring-slate-200 data-[active=true]:bg-slate-900 data-[active=true]:text-white data-[active=true]:ring-slate-900"
                >
                  All categories
                </FilterChip>
                {ISSUE_CATEGORIES.map((c) => (
                  <FilterChip
                    key={c}
                    active={category === c}
                    onClick={() => setCategory(category === c ? "" : c)}
                    className="bg-white text-slate-600 ring-slate-200 data-[active=true]:bg-sky-600 data-[active=true]:text-white data-[active=true]:ring-sky-600"
                  >
                    {labelCategory(c)}
                  </FilterChip>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Results */}
        <Card>
          <CardContent className="p-0">
            {loading && items.length === 0 ? (
              <div className="flex items-center gap-3 px-6 py-12 text-sm text-slate-500">
                <span className="h-4 w-4 animate-pulse rounded-full bg-slate-200" />
                Loading issues…
              </div>
            ) : visibleItems.length === 0 && !error ? (
              <div className="px-6 py-14 text-center">
                <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-50 text-slate-400 ring-1 ring-inset ring-slate-200">
                  <ListChecks className="h-5 w-5" />
                </div>
                <p className="mt-4 text-sm font-semibold text-slate-900">No matching issues</p>
                <p className="mt-1 text-sm text-slate-500">
                  Try clearing filters or searching a different term.
                </p>
              </div>
            ) : (
              <ul className="divide-y divide-slate-100">
                {visibleItems.map((issue) => {
                  const open = expandedId === issue.id;
                  return (
                    <li key={issue.id}>
                      <button
                        type="button"
                        onClick={() => setExpandedId(open ? null : issue.id)}
                        className={`flex w-full items-start gap-3 px-5 py-4 text-left transition hover:bg-slate-50/80 ${
                          open ? "bg-sky-50/40" : ""
                        }`}
                      >
                        <span
                          className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${
                            open
                              ? "bg-sky-100 text-sky-700"
                              : "bg-slate-100 text-slate-400"
                          }`}
                        >
                          {open ? (
                            <ChevronDown className="h-4 w-4" />
                          ) : (
                            <ChevronRight className="h-4 w-4" />
                          )}
                        </span>

                        <div className="min-w-0 flex-1 space-y-2">
                          <div className="flex flex-wrap items-center gap-2">
                            <SeverityBadge severity={issue.severity} />
                            <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] font-semibold capitalize text-slate-600">
                              {labelCategory(issue.category)}
                            </span>
                            <span className="rounded-md bg-white px-2 py-0.5 font-mono text-[11px] text-slate-400 ring-1 ring-inset ring-slate-200">
                              {issue.rule_id}
                            </span>
                          </div>
                          <p className="text-sm font-semibold leading-snug text-slate-900">
                            {issue.message}
                          </p>
                          <p
                            className="truncate text-xs text-slate-500"
                            title={issue.target_url ?? undefined}
                          >
                            {issue.target_url ?? "Site-level finding"}
                          </p>
                        </div>
                      </button>

                      {open ? (
                        <div className="border-t border-slate-100 bg-slate-50/70 px-5 py-5 sm:pl-16">
                          <IssueDetails details={issue.page_details} />
                        </div>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            )}
            <PaginationBar page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
          </CardContent>
        </Card>
      </div>
    </PageShell>
  );
}

function FilterChip({
  children,
  active,
  onClick,
  className,
}: {
  children: ReactNode;
  active: boolean;
  onClick: () => void;
  className: string;
}) {
  return (
    <button
      type="button"
      data-active={active}
      onClick={onClick}
      className={`inline-flex items-center rounded-full px-3 py-1.5 text-xs font-semibold ring-1 ring-inset transition ${className}`}
    >
      {children}
    </button>
  );
}

function IssueDetails({ details }: { details: PageDetails | null }) {
  if (!details) {
    return (
      <p className="text-sm text-slate-500">No page details attached to this finding.</p>
    );
  }

  const vitals = details.vitals;
  const rows: { label: string; value: string }[] = [
    { label: "URL", value: details.url },
    { label: "Title", value: details.title ?? "—" },
    { label: "Meta description", value: details.meta_description ?? "—" },
    { label: "Canonical", value: details.canonical_url ?? "—" },
    { label: "Status code", value: details.status_code != null ? String(details.status_code) : "—" },
    { label: "Word count", value: details.word_count != null ? String(details.word_count) : "—" },
    {
      label: "Response time",
      value: details.response_time_ms != null ? `${Math.round(details.response_time_ms)} ms` : "—",
    },
  ];

  if (vitals) {
    rows.push(
      {
        label: "Mobile performance",
        value: vitals.mobile_performance_score != null ? String(vitals.mobile_performance_score) : "—",
      },
      {
        label: "Mobile LCP",
        value: vitals.mobile_lcp_ms != null ? `${Math.round(vitals.mobile_lcp_ms)} ms` : "—",
      },
      {
        label: "Desktop performance",
        value: vitals.desktop_performance_score != null ? String(vitals.desktop_performance_score) : "—",
      },
      {
        label: "Desktop LCP",
        value: vitals.desktop_lcp_ms != null ? `${Math.round(vitals.desktop_lcp_ms)} ms` : "—",
      },
    );
  }

  return (
    <div className="space-y-3">
      <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
        Page details
      </div>
      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map((row) => (
          <div
            key={row.label}
            className="rounded-2xl border border-slate-200/80 bg-white px-3.5 py-3 shadow-sm"
          >
            <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              {row.label}
            </dt>
            <dd className="mt-1.5 break-words text-sm font-medium text-slate-900">{row.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
