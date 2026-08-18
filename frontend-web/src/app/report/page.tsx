"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ArrowRightLeft,
  Download,
  FileSpreadsheet,
  FileText,
  Printer,
  Sparkles,
} from "lucide-react";
import {
  PolarAngleAxis,
  RadialBar,
  RadialBarChart,
  ResponsiveContainer,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import {
  labelCategory,
  PageShell,
  relativeScoreColor,
  scoreColor,
  SEVERITIES,
  SeverityBadge,
} from "@/components/PageShell";
import {
  apiClient,
  downloadCrawlExport,
  type AuditReport,
  type CrawlRun,
  type CrawlRunDiff,
  type DiffIssue,
  type ExportFormat,
} from "@/lib/api";
import { useAuditSelection } from "@/lib/AuditSelectionContext";
import { formatBackendError, shouldLinkToSettings } from "@/lib/errors";
import { formatDate, formatScore } from "@/lib/format";

type ExportBusy = ExportFormat | null;
type DiffBucket = "new" | "resolved" | "persisting";

const SEVERITY_COLORS: Record<string, string> = {
  critical: "#dc2626",
  high: "#ea580c",
  medium: "#d97706",
  low: "#0284c7",
};

export default function ReportPage() {
  const { projectId, crawlRunId, ready } = useAuditSelection();
  const [report, setReport] = useState<AuditReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [exportBusy, setExportBusy] = useState<ExportBusy>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const [previousRun, setPreviousRun] = useState<CrawlRun | null>(null);
  const [compareEnabled, setCompareEnabled] = useState(false);
  const [diff, setDiff] = useState<CrawlRunDiff | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffError, setDiffError] = useState<string | null>(null);
  const [activeBucket, setActiveBucket] = useState<DiffBucket>("new");

  useEffect(() => {
    if (!ready || !crawlRunId) return;
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      setUnreachable(false);
      setExportError(null);
      setCompareEnabled(false);
      setDiff(null);
      setDiffError(null);
      setPreviousRun(null);
      try {
        const res = await apiClient.getReport(crawlRunId!);
        if (cancelled) return;
        setReport(res);

        const resolvedProjectId = projectId ?? res.project.id;
        const runs = await apiClient.listCrawlRuns({
          project_id: resolvedProjectId,
          page: 1,
          page_size: 100,
        });
        if (cancelled) return;
        const ordered = [...runs.items].sort((a, b) => {
          const aDate = a.finished_at ?? a.started_at ?? "";
          const bDate = b.finished_at ?? b.started_at ?? "";
          if (aDate !== bDate) return aDate.localeCompare(bDate);
          return a.id - b.id;
        });
        const currentIndex = ordered.findIndex((run) => run.id === crawlRunId);
        const prior = currentIndex > 0 ? ordered[currentIndex - 1] : null;
        setPreviousRun(prior);
      } catch (err) {
        if (cancelled) return;
        setUnreachable(shouldLinkToSettings(err));
        setError(formatBackendError(err));
        setReport(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [ready, crawlRunId, projectId]);

  useEffect(() => {
    if (!compareEnabled || !crawlRunId || !previousRun) {
      setDiff(null);
      setDiffError(null);
      setDiffLoading(false);
      return;
    }

    let cancelled = false;
    async function loadDiff() {
      setDiffLoading(true);
      setDiffError(null);
      try {
        const result = await apiClient.getCrawlRunDiff(crawlRunId!, previousRun!.id);
        if (!cancelled) {
          setDiff(result);
          setActiveBucket("new");
        }
      } catch (err) {
        if (!cancelled) {
          setDiff(null);
          setDiffError(formatBackendError(err));
        }
      } finally {
        if (!cancelled) setDiffLoading(false);
      }
    }

    void loadDiff();
    return () => {
      cancelled = true;
    };
  }, [compareEnabled, crawlRunId, previousRun]);

  async function handleExport(format: ExportFormat) {
    if (!crawlRunId || exportBusy) return;
    setExportBusy(format);
    setExportError(null);
    try {
      await downloadCrawlExport(crawlRunId, format);
    } catch (err) {
      setExportError(formatBackendError(err));
    } finally {
      setExportBusy(null);
    }
  }

  const categoryEntries = useMemo(() => {
    const rows = Object.entries(report?.category_scores ?? {})
      .map(([category, score]) => ({
        category,
        label: labelCategory(category),
        score: Math.round(score),
      }))
      .sort((a, b) => a.score - b.score || a.label.localeCompare(b.label));

    if (rows.length === 0) return [];
    const minScore = rows[0].score;
    const maxScore = rows[rows.length - 1].score;
    return rows.map((row) => ({
      ...row,
      fill:
        maxScore === minScore
          ? scoreColor(row.score)
          : relativeScoreColor(row.score, minScore, maxScore),
    }));
  }, [report]);

  const severityRows = useMemo(() => {
    if (!report) return [];
    return SEVERITIES.map((key) => ({
      key,
      count: report.summary.issues_by_severity[key] ?? 0,
      fill: SEVERITY_COLORS[key],
    }));
  }, [report]);

  const totalSeverity = severityRows.reduce((acc, row) => acc + row.count, 0);
  const urgentCount =
    (report?.summary.issues_by_severity.critical ?? 0) +
    (report?.summary.issues_by_severity.high ?? 0);

  const gaugeData = useMemo(
    () => [
      {
        name: "score",
        value: Math.max(0, Math.min(100, report?.overall_score ?? 0)),
        fill: scoreColor(report?.overall_score),
      },
    ],
    [report?.overall_score],
  );

  const anyExportBusy = exportBusy !== null;

  const bucketIssues = useMemo(() => {
    if (!diff) return [];
    if (activeBucket === "new") return diff.new_issues;
    if (activeBucket === "resolved") return diff.resolved_issues;
    return diff.persisting_issues;
  }, [diff, activeBucket]);

  return (
    <PageShell
      title="Report"
      subtitle={
        crawlRunId
          ? `Shareable audit report for run #${crawlRunId}`
          : "No audit selected."
      }
      crawlRunId={crawlRunId}
      ready={ready}
      loading={loading}
      error={error}
      unreachable={unreachable}
    >
      {exportError ? (
        <div className="print:hidden rounded-2xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-800">
          {exportError}
        </div>
      ) : null}

      {report ? (
        <div className="report-print space-y-6">
          {/* Cover / hero */}
          <section className="overflow-hidden rounded-3xl border border-slate-200/80 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
            <div className="relative overflow-hidden border-b border-slate-100 bg-[radial-gradient(circle_at_0%_0%,rgba(14,165,233,0.16),transparent_42%),radial-gradient(circle_at_100%_0%,rgba(16,185,129,0.12),transparent_40%),linear-gradient(180deg,#f8fafc_0%,#ffffff_70%)] px-6 py-8 lg:px-10 lg:py-10">
              <div className="flex flex-wrap items-start justify-between gap-6">
                <div className="min-w-0 max-w-2xl">
                  <div className="inline-flex items-center gap-2 rounded-full bg-white/80 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-sky-700 ring-1 ring-inset ring-sky-100">
                    <Sparkles className="h-3.5 w-3.5" />
                    SEO Audit Report
                  </div>
                  <h2 className="mt-4 truncate text-3xl font-semibold tracking-tight text-slate-900 lg:text-4xl">
                    {report.project.domain ?? "Unknown domain"}
                  </h2>
                  <p className="mt-2 text-sm leading-relaxed text-slate-500">
                    Crawl date {formatDate(report.crawl_date)} · Run #{crawlRunId}
                  </p>
                  <p className="mt-3 text-sm font-medium text-slate-700">
                    {report.summary.summary_text}
                  </p>
                  <div className="mt-6 grid max-w-2xl grid-cols-2 gap-3 sm:grid-cols-4">
                    <MiniStat label="Pages" value={String(report.summary.total_pages)} />
                    <MiniStat
                      label="Site issues"
                      value={String(report.summary.site_issue_count)}
                    />
                    <MiniStat
                      label="Pages w/ issues"
                      value={String(report.summary.pages_with_issues)}
                    />
                    <MiniStat
                      label="Page findings"
                      value={String(report.summary.page_issue_count)}
                      accent={urgentCount > 0}
                    />
                  </div>
                </div>

                <div className="mx-auto w-44 shrink-0 sm:mx-0">
                  <div className="relative h-44 w-44">
                    <ResponsiveContainer width="100%" height="100%">
                      <RadialBarChart
                        cx="50%"
                        cy="50%"
                        innerRadius="78%"
                        outerRadius="100%"
                        data={gaugeData}
                        startAngle={90}
                        endAngle={-270}
                      >
                        <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
                        <RadialBar background={{ fill: "#e2e8f0" }} dataKey="value" cornerRadius={14} />
                      </RadialBarChart>
                    </ResponsiveContainer>
                    <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                      <div
                        className="text-4xl font-semibold tabular-nums tracking-tight"
                        style={{ color: scoreColor(report.overall_score) }}
                      >
                        {formatScore(report.overall_score)}
                      </div>
                      <div className="mt-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                        Overall
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Export strip */}
            <div className="print:hidden grid gap-3 border-t border-slate-100 bg-slate-50/60 p-4 sm:grid-cols-2 lg:grid-cols-4 lg:p-5">
              <ExportCard
                title="PDF report"
                description="Polished client-ready export"
                icon={FileText}
                busy={exportBusy === "pdf"}
                disabled={anyExportBusy}
                primary
                onClick={() => void handleExport("pdf")}
              />
              <ExportCard
                title="CSV data"
                description="Raw findings spreadsheet"
                icon={Download}
                busy={exportBusy === "csv"}
                disabled={anyExportBusy}
                onClick={() => void handleExport("csv")}
              />
              <ExportCard
                title="Excel workbook"
                description="Formatted XLSX download"
                icon={FileSpreadsheet}
                busy={exportBusy === "xlsx"}
                disabled={anyExportBusy}
                onClick={() => void handleExport("xlsx")}
              />
              <ExportCard
                title="Print view"
                description="Browser print / save PDF"
                icon={Printer}
                busy={false}
                disabled={anyExportBusy}
                onClick={() => window.print()}
              />
            </div>
          </section>

          {/* Severity + categories */}
          <div className="grid gap-6 xl:grid-cols-12">
            <Card className="xl:col-span-5">
              <CardHeader>
                <CardTitle>Severity overview</CardTitle>
                <p className="mt-1 text-xs text-slate-500">Issue volume across priority levels</p>
              </CardHeader>
              <CardContent className="space-y-5">
                {totalSeverity === 0 ? (
                  <p className="py-6 text-center text-sm text-slate-500">No issues in this report.</p>
                ) : (
                  <>
                    <div className="flex h-3 overflow-hidden rounded-full bg-slate-100">
                      {severityRows
                        .filter((row) => row.count > 0)
                        .map((row) => (
                          <div
                            key={row.key}
                            className="h-full first:rounded-l-full last:rounded-r-full"
                            style={{
                              width: `${(row.count / totalSeverity) * 100}%`,
                              backgroundColor: row.fill,
                            }}
                          />
                        ))}
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      {severityRows.map((row) => (
                        <div
                          key={row.key}
                          className="rounded-2xl border border-slate-200/80 bg-slate-50/70 px-4 py-3"
                        >
                          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                            <span
                              className="h-2 w-2 rounded-full"
                              style={{ backgroundColor: row.fill }}
                            />
                            {row.key}
                          </div>
                          <div
                            className="mt-2 text-2xl font-semibold tabular-nums"
                            style={{ color: row.fill }}
                          >
                            {row.count}
                          </div>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </CardContent>
            </Card>

            <Card className="xl:col-span-7">
              <CardHeader>
                <CardTitle>Category scores</CardTitle>
                <p className="mt-1 text-xs text-slate-500">
                  Relative health coloring within this audit
                </p>
              </CardHeader>
              <CardContent>
                {categoryEntries.length === 0 ? (
                  <p className="py-6 text-center text-sm text-slate-500">No category scores yet.</p>
                ) : (
                  <div className="space-y-2">
                    {categoryEntries.map((row) => (
                      <div
                        key={row.category}
                        className="rounded-2xl px-3 py-3"
                        style={{
                          backgroundColor: `${row.fill}12`,
                          boxShadow: `inset 0 0 0 1px ${row.fill}2e`,
                        }}
                      >
                        <div className="flex items-center justify-between gap-3">
                          <span className="text-sm font-semibold capitalize text-slate-900">
                            {row.label}
                          </span>
                          <span
                            className="text-sm font-bold tabular-nums"
                            style={{ color: row.fill }}
                          >
                            {row.score}
                          </span>
                        </div>
                        <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/80">
                          <div
                            className="h-full rounded-full"
                            style={{ width: `${row.score}%`, backgroundColor: row.fill }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Compare */}
          <section className="print:hidden break-inside-avoid">
            <Card>
              <CardContent className="space-y-5 py-6">
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div className="flex items-start gap-3">
                    <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-sky-50 text-sky-600 ring-1 ring-inset ring-sky-100">
                      <ArrowRightLeft className="h-4 w-4" />
                    </span>
                    <div>
                      <h2 className="text-base font-semibold text-slate-900">
                        Compare to previous audit
                      </h2>
                      <p className="mt-1 text-sm text-slate-500">
                        {previousRun
                          ? `Prior run #${previousRun.id}${
                              previousRun.finished_at || previousRun.started_at
                                ? ` · ${formatDate(previousRun.finished_at ?? previousRun.started_at)}`
                                : ""
                            }`
                          : "No earlier scored run is available for this project."}
                      </p>
                    </div>
                  </div>
                  <button
                    type="button"
                    disabled={!previousRun}
                    onClick={() => setCompareEnabled((v) => !v)}
                    className={`relative inline-flex h-8 w-14 items-center rounded-full transition ${
                      !previousRun
                        ? "cursor-not-allowed bg-slate-200"
                        : compareEnabled
                          ? "bg-sky-600"
                          : "bg-slate-300"
                    }`}
                    aria-pressed={compareEnabled}
                  >
                    <span
                      className={`inline-block h-6 w-6 transform rounded-full bg-white shadow transition ${
                        compareEnabled ? "translate-x-7" : "translate-x-1"
                      }`}
                    />
                  </button>
                </div>

                {compareEnabled ? (
                  <div className="space-y-5">
                    {diffLoading ? (
                      <p className="text-sm text-slate-500">Loading issue diff…</p>
                    ) : null}
                    {diffError ? (
                      <p className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
                        {diffError}
                      </p>
                    ) : null}
                    {diff ? (
                      <>
                        <div className="grid gap-3 sm:grid-cols-3">
                          {(
                            [
                              ["new", "New", diff.counts.new, "#dc2626"],
                              ["resolved", "Resolved", diff.counts.resolved, "#059669"],
                              ["persisting", "Persisting", diff.counts.persisting, "#d97706"],
                            ] as const
                          ).map(([key, label, count, color]) => (
                            <button
                              key={key}
                              type="button"
                              onClick={() => setActiveBucket(key)}
                              className={`rounded-2xl border px-4 py-4 text-left transition ${
                                activeBucket === key
                                  ? "border-slate-900 bg-slate-900 text-white shadow-sm"
                                  : "border-slate-200 bg-white hover:border-slate-300"
                              }`}
                            >
                              <div
                                className={`text-[11px] font-semibold uppercase tracking-wide ${
                                  activeBucket === key ? "text-slate-300" : "text-slate-500"
                                }`}
                              >
                                {label}
                              </div>
                              <div
                                className="mt-1 text-3xl font-semibold tabular-nums"
                                style={{ color: activeBucket === key ? "#fff" : color }}
                              >
                                {count}
                              </div>
                            </button>
                          ))}
                        </div>
                        <DiffIssueList issues={bucketIssues} emptyLabel={`No ${activeBucket} issues.`} />
                      </>
                    ) : null}
                  </div>
                ) : null}
              </CardContent>
            </Card>
          </section>

          {/* Recommendations */}
          <section className="break-inside-avoid">
            <div className="mb-4">
              <h2 className="text-lg font-semibold tracking-tight text-slate-900">
                Prioritized recommendations
              </h2>
              <p className="mt-1 text-sm text-slate-500">
                Ranked by severity weight × pages affected — start at the top for maximum impact.
              </p>
            </div>
            {report.recommendations.length === 0 ? (
              <Card>
                <CardContent className="py-10 text-center text-sm text-slate-500">
                  No prioritized recommendations for this run.
                </CardContent>
              </Card>
            ) : (
              <div className="space-y-3">
                {report.recommendations.map((rec, index) => (
                  <div
                    key={`${rec.rule}-${index}`}
                    className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-slate-900 text-xs font-bold text-white">
                        {index + 1}
                      </span>
                      <SeverityBadge severity={rec.severity} />
                      <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] font-semibold capitalize text-slate-600">
                        {labelCategory(rec.category)}
                      </span>
                      <span className="text-xs font-medium text-slate-400">
                        {rec.pages_affected} page{rec.pages_affected === 1 ? "" : "s"}
                      </span>
                      <span className="rounded-md bg-slate-50 px-2 py-0.5 font-mono text-[11px] text-slate-400 ring-1 ring-inset ring-slate-200">
                        {rec.rule}
                      </span>
                    </div>
                    <p className="mt-3 text-sm font-medium leading-relaxed text-slate-900">
                      {rec.message}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* Findings — site vs page, never mixed / never duplicated */}
          <section>
            <div className="mb-4">
              <h2 className="text-lg font-semibold tracking-tight text-slate-900">
                Site Issues
              </h2>
              <p className="mt-1 text-sm text-slate-500">
                One row per site-level finding (robots, sitemap, cross-page, homepage). Never
                repeated under individual pages.
              </p>
            </div>
            <Card className="break-inside-avoid overflow-hidden">
              <CardContent className="p-0">
                {(report.site_issues ?? []).length === 0 ? (
                  <p className="px-6 py-8 text-sm text-slate-500">No site issues for this run.</p>
                ) : (
                  <ul className="divide-y divide-slate-100">
                    {report.site_issues.map((issue) => (
                      <li key={issue.id} className="px-5 py-4 sm:px-6">
                        <div className="flex flex-wrap items-center gap-2">
                          <SeverityBadge severity={issue.severity} />
                          <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] font-semibold capitalize text-slate-600">
                            {labelCategory(issue.category)}
                          </span>
                          <span className="rounded-full bg-indigo-50 px-2.5 py-0.5 text-[11px] font-semibold capitalize text-indigo-700 ring-1 ring-inset ring-indigo-100">
                            {issue.scope.replace(/_/g, " ")}
                          </span>
                          <span className="rounded-md bg-slate-50 px-2 py-0.5 font-mono text-[11px] text-slate-400 ring-1 ring-inset ring-slate-200">
                            {issue.rule}
                          </span>
                        </div>
                        <p className="mt-2 text-sm font-semibold text-slate-900">{issue.message}</p>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </section>

          <section>
            <div className="mb-4">
              <h2 className="text-lg font-semibold tracking-tight text-slate-900">
                Page Issues
              </h2>
              <p className="mt-1 text-sm text-slate-500">
                Grouped by URL — only that page&apos;s rows from page_issues.
              </p>
            </div>
            {(report.page_issues ?? []).length === 0 ? (
              <Card>
                <CardContent className="py-10 text-center text-sm text-slate-500">
                  No page-level findings for this run.
                </CardContent>
              </Card>
            ) : (
              <div className="space-y-4">
                {report.page_issues.map((group) => (
                  <Card key={group.url} className="break-inside-avoid overflow-hidden">
                    <CardHeader className="flex flex-row items-start justify-between gap-3 bg-slate-50/80">
                      <div className="min-w-0">
                        <CardTitle className="truncate text-base" title={group.url}>
                          {group.url}
                        </CardTitle>
                        <p className="mt-1 text-xs text-slate-500">
                          {group.issue_count} finding{group.issue_count === 1 ? "" : "s"}
                        </p>
                      </div>
                    </CardHeader>
                    <CardContent className="p-0">
                      <ul className="divide-y divide-slate-100">
                        {group.issues.map((issue) => (
                          <li key={issue.id} className="px-5 py-4 sm:px-6">
                            <div className="flex flex-wrap items-center gap-2">
                              <SeverityBadge severity={issue.severity} />
                              <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-[11px] font-semibold capitalize text-slate-600">
                                {labelCategory(issue.category)}
                              </span>
                              <span className="rounded-md bg-slate-50 px-2 py-0.5 font-mono text-[11px] text-slate-400 ring-1 ring-inset ring-slate-200">
                                {issue.rule}
                              </span>
                            </div>
                            <p className="mt-2 text-sm font-semibold text-slate-900">
                              {issue.message}
                            </p>
                          </li>
                        ))}
                      </ul>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </section>
        </div>
      ) : null}
    </PageShell>
  );
}

function MiniStat({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div className="rounded-2xl border border-white/70 bg-white/80 px-3 py-3 shadow-sm backdrop-blur">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{label}</div>
      <div
        className={`mt-1 text-xl font-semibold tabular-nums ${
          accent ? "text-orange-600" : "text-slate-900"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function ExportCard({
  title,
  description,
  icon: Icon,
  busy,
  disabled,
  onClick,
  primary = false,
}: {
  title: string;
  description: string;
  icon: typeof FileText;
  busy: boolean;
  disabled: boolean;
  onClick: () => void;
  primary?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`flex items-start gap-3 rounded-2xl border px-4 py-3.5 text-left transition disabled:cursor-not-allowed disabled:opacity-60 ${
        primary
          ? "border-sky-200 bg-sky-600 text-white shadow-sm hover:bg-sky-700"
          : "border-slate-200 bg-white text-slate-800 hover:border-slate-300 hover:bg-slate-50"
      }`}
    >
      <span
        className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${
          primary ? "bg-white/15 text-white" : "bg-slate-50 text-slate-500 ring-1 ring-inset ring-slate-200"
        }`}
      >
        {busy ? (
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-r-transparent" />
        ) : (
          <Icon className="h-4 w-4" />
        )}
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-semibold">{busy ? "Preparing…" : title}</span>
        <span className={`mt-0.5 block text-xs ${primary ? "text-sky-100" : "text-slate-500"}`}>
          {description}
        </span>
      </span>
    </button>
  );
}

function DiffIssueList({ issues, emptyLabel }: { issues: DiffIssue[]; emptyLabel: string }) {
  if (issues.length === 0) {
    return <p className="text-sm text-slate-500">{emptyLabel}</p>;
  }

  return (
    <ul className="divide-y divide-slate-100 overflow-hidden rounded-2xl border border-slate-200 bg-white">
      {issues.map((issue, index) => (
        <li key={`${issue.rule_id}-${issue.target_url}-${index}`} className="px-4 py-3.5">
          <div className="flex flex-wrap items-center gap-2">
            <SeverityBadge severity={issue.severity} />
            <span className="rounded-md bg-slate-50 px-2 py-0.5 font-mono text-[11px] text-slate-400 ring-1 ring-inset ring-slate-200">
              {issue.rule_id}
            </span>
          </div>
          <p className="mt-2 text-sm font-medium text-slate-900">{issue.message}</p>
          <p className="mt-1 truncate text-xs text-slate-500" title={issue.target_url ?? undefined}>
            {issue.target_url ?? "—"}
          </p>
        </li>
      ))}
    </ul>
  );
}
