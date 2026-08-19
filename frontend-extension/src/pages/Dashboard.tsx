import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  FileSearch,
  Gauge,
  Layers,
  ListChecks,
  TrendingUp,
} from "lucide-react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  PolarAngleAxis,
  RadialBar,
  RadialBarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import {
  labelCategory,
  PageShell,
  relativeScoreColor,
  RunContextLinks,
  scoreColor,
  SEVERITIES,
} from "@/components/PageShell";
import {
  apiClient,
  type CrawlRunSummary,
  type Project,
  type ScoreHistoryItem,
} from "@/lib/api";
import { useAuditSelection } from "@/lib/AuditSelectionContext";
import { ApiError, formatBackendError, shouldLinkToSettings } from "@/lib/errors";
import { formatDate, formatScore, StatusPill } from "@/lib/format";

const SEVERITY_COLORS: Record<string, string> = {
  critical: "#dc2626",
  high: "#ea580c",
  medium: "#d97706",
  low: "#0284c7",
};

const HISTORY_LINE_COLORS = [
  "#0f172a",
  "#0284c7",
  "#0d9488",
  "#d97706",
  "#475569",
  "#0369a1",
  "#059669",
  "#b45309",
  "#334155",
  "#64748b",
];

function healthLabel(score: number | null): { label: string; tone: string } {
  if (score == null) return { label: "Awaiting score", tone: "text-slate-500" };
  if (score >= 80) return { label: "Strong health", tone: "text-emerald-600" };
  if (score >= 60) return { label: "Needs attention", tone: "text-sky-600" };
  if (score >= 40) return { label: "At risk", tone: "text-amber-600" };
  return { label: "Critical gaps", tone: "text-red-600" };
}

export default function DashboardPage() {
  const { projectId, crawlRunId, ready, selectAudit, clearSelection } = useAuditSelection();
  const [project, setProject] = useState<Project | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [summary, setSummary] = useState<CrawlRunSummary | null>(null);
  const [scoreHistory, setScoreHistory] = useState<ScoreHistoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unreachable, setUnreachable] = useState(false);

  useEffect(() => {
    if (!ready || !crawlRunId) return;
    let cancelled = false;
    let timer: number | null = null;

    async function load(isFirst: boolean = true) {
      if (isFirst) setLoading(true);
      setError(null);
      setUnreachable(false);
      try {
        const [run, sum] = await Promise.all([
          apiClient.getCrawlRun(crawlRunId!),
          apiClient.getSummary(crawlRunId!),
        ]);
        if (cancelled) return;
        setStatus(run.status);
        setSummary(sum);

        const resolvedProjectId = projectId ?? run.project_id;
        const [projects, history] = await Promise.all([
          apiClient.listProjects({ page: 1, page_size: 200 }),
          apiClient.getScoreHistory(resolvedProjectId),
        ]);
        if (cancelled) return;
        setProject(projects.items.find((p) => p.id === resolvedProjectId) ?? null);
        setScoreHistory(history.items);

        if (["pending", "running", "enriching", "crawling"].includes(run.status)) {
          timer = window.setTimeout(() => void load(false), 2000);
        }
      } catch (err) {
        if (cancelled) return;

        // If the selected run doesn't exist on this backend (e.g. switched from remote to local),
        // automatically fallback to the latest run available on this backend.
        if (err instanceof ApiError && err.status === 404) {
          try {
            const runs = await apiClient.listCrawlRuns({ page: 1, page_size: 1 });
            if (runs.items.length > 0) {
              await selectAudit(runs.items[0].project_id, runs.items[0].id);
              return;
            } else {
              await clearSelection();
              return;
            }
          } catch {
            /* fall through */
          }
        }

        setUnreachable(shouldLinkToSettings(err));
        setError(formatBackendError(err));
        if (isFirst) {
          setSummary(null);
          setScoreHistory([]);
        }
        // Retry polling so temporary server reloads automatically resolve
        timer = window.setTimeout(() => void load(false), 3000);
      } finally {
        if (!cancelled && isFirst) setLoading(false);
      }
    }

    void load(true);
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [ready, crawlRunId, projectId]);

  const overall = summary?.overall_score ?? null;
  const health = healthLabel(overall);

  const gaugeData = useMemo(
    () => [{ name: "score", value: Math.max(0, Math.min(100, overall ?? 0)), fill: scoreColor(overall) }],
    [overall],
  );

  const categoryData = useMemo(() => {
    const rows = Object.entries(summary?.category_scores ?? {})
      .map(([category, score]) => ({
        category,
        label: labelCategory(category),
        score: Math.round(score),
      }))
      .sort((a, b) => a.score - b.score || a.label.localeCompare(b.label));

    if (rows.length === 0) return [];

    const minScore = rows[0].score;
    const maxScore = rows[rows.length - 1].score;

    return rows.map((row, index) => {
      // Prefer relative spread so close high scores (87–100) stay visually distinct.
      const fill =
        maxScore === minScore
          ? scoreColor(row.score)
          : relativeScoreColor(row.score, minScore, maxScore);
      return {
        ...row,
        fill,
        rank: index + 1,
        isFocus: index < Math.min(2, rows.length),
        gapFromBest: maxScore - row.score,
      };
    });
  }, [summary]);

  const severityData = useMemo(
    () =>
      SEVERITIES.map((key) => ({
        severity: key,
        count: summary?.total_issues_by_severity?.[key] ?? 0,
        fill: SEVERITY_COLORS[key],
      })),
    [summary],
  );

  const historyCategories = useMemo(() => {
    const keys = new Set<string>();
    for (const item of scoreHistory) {
      for (const category of Object.keys(item.category_scores)) {
        keys.add(category);
      }
    }
    return Array.from(keys).sort((a, b) => labelCategory(a).localeCompare(labelCategory(b)));
  }, [scoreHistory]);

  const historyChartData = useMemo(
    () =>
      scoreHistory.map((item) => {
        const row: Record<string, string | number | null> = {
          label: item.date ? formatDate(item.date) : `Run #${item.crawl_run_id}`,
          runId: item.crawl_run_id,
          overall: item.overall_score,
        };
        for (const category of historyCategories) {
          row[category] = item.category_scores[category] ?? null;
        }
        return row;
      }),
    [scoreHistory, historyCategories],
  );

  const totalIssues = severityData.reduce((acc, row) => acc + row.count, 0);
  const urgentIssues =
    (summary?.total_issues_by_severity?.critical ?? 0) +
    (summary?.total_issues_by_severity?.high ?? 0);
  const weakest = categoryData[0] ?? null;
  const strongest = categoryData.length ? categoryData[categoryData.length - 1] : null;

  return (
    <PageShell
      title="Dashboard"
      subtitle={
        crawlRunId
          ? `Audit analysis for ${project?.domain ?? `project #${projectId}`} · Run #${crawlRunId}`
          : "No audit selected."
      }
      actions={
        crawlRunId ? (
          <>
            {status ? <StatusPill status={status} /> : null}
            <RunContextLinks projectId={projectId} />
          </>
        ) : undefined
      }
      crawlRunId={crawlRunId}
      ready={ready}
      loading={loading}
      error={error}
      unreachable={unreachable}
    >
      {summary ? (
        <div className="space-y-6">
          {/* Health hero */}
          <section className="overflow-hidden rounded-3xl border border-slate-200/80 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
            <div className="grid lg:grid-cols-[280px_1fr]">
              <div className="relative border-b border-slate-100 bg-[radial-gradient(circle_at_30%_20%,rgba(14,165,233,0.12),transparent_55%),linear-gradient(180deg,#f8fafc_0%,#ffffff_100%)] px-6 py-8 lg:border-b-0 lg:border-r">
                <div className="mb-4 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                  <Gauge className="h-3.5 w-3.5" />
                  Overall health
                </div>
                <div className="relative mx-auto h-48 w-48">
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
                      className="text-5xl font-semibold tabular-nums tracking-tight"
                      style={{ color: scoreColor(overall) }}
                    >
                      {formatScore(overall)}
                    </div>
                    <div className="mt-1 text-[11px] font-medium uppercase tracking-wider text-slate-400">
                      / 100
                    </div>
                  </div>
                </div>
                <div className={`mt-4 text-center text-sm font-semibold ${health.tone}`}>
                  {health.label}
                </div>
              </div>

              <div className="flex flex-col justify-between gap-6 px-6 py-7 lg:px-8">
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                    Site under review
                  </div>
                  <h2 className="mt-2 truncate text-2xl font-semibold tracking-tight text-slate-900">
                    {project?.domain ?? `Project #${projectId}`}
                  </h2>
                  <p className="mt-2 max-w-xl text-sm leading-relaxed text-slate-500">
                    Ranked category health, severity mix, and score trends for this crawl run.
                    Fix urgent issues first, then lift the weakest categories.
                  </p>
                </div>

                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <KpiTile
                    icon={FileSearch}
                    label="Pages crawled"
                    value={String(summary.total_pages)}
                    hint="Indexed in this run"
                  />
                  <KpiTile
                    icon={ListChecks}
                    label="Total issues"
                    value={String(totalIssues)}
                    hint="Across all severities"
                  />
                  <KpiTile
                    icon={AlertTriangle}
                    label="Urgent"
                    value={String(urgentIssues)}
                    hint="Critical + high"
                    accent="text-orange-600"
                  />
                  <KpiTile
                    icon={Layers}
                    label="Weakest area"
                    value={weakest ? String(weakest.score) : "—"}
                    hint={weakest ? weakest.label : "No scores yet"}
                    accent={weakest ? undefined : "text-slate-900"}
                    valueColor={weakest?.fill}
                  />
                </div>
              </div>
            </div>
          </section>

          <div className="grid gap-6 xl:grid-cols-12">
            {/* Severity analysis */}
            <Card className="xl:col-span-5">
              <CardHeader className="flex flex-row items-center justify-between gap-3">
                <div>
                  <CardTitle>Severity mix</CardTitle>
                  <p className="mt-1 text-xs text-slate-500">Issue volume by priority</p>
                </div>
                <Link
                  to="/issues"
                  className="inline-flex items-center gap-1 text-sm font-semibold text-brand-700 hover:underline"
                >
                  Open issues <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              </CardHeader>
              <CardContent className="space-y-5">
                {totalIssues === 0 ? (
                  <p className="py-8 text-center text-sm text-slate-500">No issues found for this run.</p>
                ) : (
                  <>
                    <div className="flex h-3 overflow-hidden rounded-full bg-slate-100">
                      {severityData
                        .filter((row) => row.count > 0)
                        .map((row) => (
                          <div
                            key={row.severity}
                            className="h-full first:rounded-l-full last:rounded-r-full"
                            style={{
                              width: `${(row.count / totalIssues) * 100}%`,
                              backgroundColor: row.fill,
                            }}
                            title={`${row.severity}: ${row.count}`}
                          />
                        ))}
                    </div>
                    <div className="space-y-3">
                      {severityData.map((row) => {
                        const pct = totalIssues ? Math.round((row.count / totalIssues) * 100) : 0;
                        return (
                          <div key={row.severity} className="flex items-center gap-3">
                            <span
                              className="h-2.5 w-2.5 shrink-0 rounded-full"
                              style={{ backgroundColor: row.fill }}
                            />
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center justify-between gap-2 text-sm">
                                <span className="font-medium capitalize text-slate-700">
                                  {row.severity}
                                </span>
                                <span className="tabular-nums text-slate-500">
                                  {row.count} · {pct}%
                                </span>
                              </div>
                              <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-100">
                                <div
                                  className="h-full rounded-full"
                                  style={{ width: `${pct}%`, backgroundColor: row.fill }}
                                />
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </>
                )}
              </CardContent>
            </Card>

            {/* Category ranking */}
            <Card className="xl:col-span-7">
              <CardHeader className="flex flex-row items-start justify-between gap-3">
                <div>
                  <CardTitle>Category health ranking</CardTitle>
                  <p className="mt-1 text-xs text-slate-500">
                    Sorted weakest → strongest · colors scale within this audit
                  </p>
                  <div className="mt-3 flex flex-wrap items-center gap-2 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                    <span className="inline-flex items-center gap-1.5">
                      <span className="h-2 w-2 rounded-full bg-red-500" /> Focus
                    </span>
                    <span className="text-slate-300">→</span>
                    <span className="inline-flex items-center gap-1.5">
                      <span className="h-2 w-2 rounded-full bg-amber-500" /> Mid
                    </span>
                    <span className="text-slate-300">→</span>
                    <span className="inline-flex items-center gap-1.5">
                      <span className="h-2 w-2 rounded-full bg-sky-500" /> Strong
                    </span>
                    <span className="text-slate-300">→</span>
                    <span className="inline-flex items-center gap-1.5">
                      <span className="h-2 w-2 rounded-full bg-emerald-500" /> Best
                    </span>
                  </div>
                </div>
                {strongest ? (
                  <div className="rounded-xl bg-emerald-50 px-3 py-2 text-right ring-1 ring-inset ring-emerald-100">
                    <div className="text-[10px] font-semibold uppercase tracking-wider text-emerald-600">
                      Strongest
                    </div>
                    <div className="mt-0.5 text-sm font-semibold capitalize text-emerald-800">
                      {strongest.label} · {strongest.score}
                    </div>
                  </div>
                ) : null}
              </CardHeader>
              <CardContent>
                {categoryData.length === 0 ? (
                  <p className="py-8 text-center text-sm text-slate-500">No category scores yet.</p>
                ) : (
                  <div className="space-y-2">
                    {categoryData.map((row) => (
                      <div
                        key={row.category}
                        className="flex items-center gap-3 rounded-2xl px-3 py-3 ring-1 ring-inset"
                        style={{
                          backgroundColor: `${row.fill}14`,
                          // ring via boxShadow so dynamic color works without Tailwind
                          boxShadow: `inset 0 0 0 1px ${row.fill}33`,
                        }}
                      >
                        <div
                          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-xs font-bold tabular-nums text-white"
                          style={{ backgroundColor: row.fill }}
                        >
                          {row.rank}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="flex min-w-0 items-center gap-2">
                              <span className="truncate text-sm font-semibold capitalize text-slate-900">
                                {row.label}
                              </span>
                              {row.isFocus ? (
                                <span className="shrink-0 rounded-full bg-white/80 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-orange-700 ring-1 ring-orange-200">
                                  Focus
                                </span>
                              ) : null}
                            </div>
                            <div className="flex shrink-0 items-baseline gap-2">
                              {row.gapFromBest > 0 ? (
                                <span className="text-[11px] font-medium tabular-nums text-slate-500">
                                  −{row.gapFromBest} vs best
                                </span>
                              ) : (
                                <span className="text-[11px] font-medium text-emerald-600">Best</span>
                              )}
                              <span
                                className="text-base font-bold tabular-nums"
                                style={{ color: row.fill }}
                              >
                                {row.score}
                              </span>
                            </div>
                          </div>
                          <div className="mt-2 h-2.5 overflow-hidden rounded-full bg-white/80">
                            <div
                              className="h-full rounded-full transition-all"
                              style={{ width: `${row.score}%`, backgroundColor: row.fill }}
                            />
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Trend */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <TrendingUp className="h-4 w-4 text-slate-400" />
                  <CardTitle>Score over time</CardTitle>
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  Overall and category scores across previous audits for this project
                </p>
              </div>
              {projectId ? (
                <Link
                  to={`/projects/${projectId}`}
                  className="inline-flex items-center gap-1 text-sm font-semibold text-brand-700 hover:underline"
                >
                  Run history <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              ) : null}
            </CardHeader>
            <CardContent>
              {historyChartData.length < 2 ? (
                <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50/70 px-6 py-10 text-center">
                  <p className="text-sm text-slate-600">
                    {historyChartData.length === 1
                      ? "Only one scored audit so far. Run another crawl to unlock trends."
                      : "No scored audits yet for this project."}
                  </p>
                  <Link
                    to="/audits/new"
                    className="mt-4 inline-flex rounded-xl bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-brand-700"
                  >
                    Start another audit
                  </Link>
                </div>
              ) : (
                <div className="h-80">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={historyChartData} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                      <CartesianGrid strokeDasharray="4 4" stroke="#e2e8f0" vertical={false} />
                      <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#64748b" }} axisLine={false} tickLine={false} />
                      <YAxis
                        domain={[0, 100]}
                        tick={{ fontSize: 12, fill: "#64748b" }}
                        width={36}
                        axisLine={false}
                        tickLine={false}
                      />
                      <Tooltip
                        contentStyle={{
                          borderRadius: 12,
                          borderColor: "#e2e8f0",
                          boxShadow: "0 8px 24px rgba(15,23,42,0.08)",
                        }}
                        formatter={(value, name) => [
                          value == null ? "—" : Math.round(Number(value)),
                          name === "overall" ? "Overall" : labelCategory(String(name)),
                        ]}
                      />
                      <Legend
                        formatter={(value) =>
                          value === "overall" ? "Overall" : labelCategory(String(value))
                        }
                      />
                      <Line
                        type="monotone"
                        dataKey="overall"
                        stroke={HISTORY_LINE_COLORS[0]}
                        strokeWidth={2.75}
                        dot={{ r: 3.5, strokeWidth: 0 }}
                        connectNulls
                      />
                      {historyCategories.map((category, index) => (
                        <Line
                          key={category}
                          type="monotone"
                          dataKey={category}
                          stroke={HISTORY_LINE_COLORS[(index + 1) % HISTORY_LINE_COLORS.length]}
                          strokeWidth={1.6}
                          strokeOpacity={0.85}
                          dot={{ r: 2, strokeWidth: 0 }}
                          connectNulls
                        />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      ) : null}

      {!loading && !summary && !error && crawlRunId ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-slate-600">
            Summary is not available yet for this run{status ? ` (status: ${status})` : ""}.
          </CardContent>
        </Card>
      ) : null}
    </PageShell>
  );
}

function KpiTile({
  icon: Icon,
  label,
  value,
  hint,
  accent,
  valueColor,
}: {
  icon: typeof FileSearch;
  label: string;
  value: string;
  hint: string;
  accent?: string;
  valueColor?: string;
}) {
  return (
    <div className="rounded-2xl border border-slate-200/80 bg-slate-50/80 px-4 py-3.5">
      <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <div
        className={`mt-2 text-2xl font-semibold tabular-nums tracking-tight ${accent ?? "text-slate-900"}`}
        style={valueColor ? { color: valueColor } : undefined}
      >
        {value}
      </div>
      <div className="mt-0.5 truncate text-xs capitalize text-slate-500">{hint}</div>
    </div>
  );
}
