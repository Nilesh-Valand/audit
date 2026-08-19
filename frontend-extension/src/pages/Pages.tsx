import { useEffect, useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { PageShell, PaginationBar } from "@/components/PageShell";
import { PageDetailDrawer } from "@/components/PageDetailDrawer";
import { apiClient, type CrawledPage, type CrawlRunProgress } from "@/lib/api";
import { useAuditSelection } from "@/lib/AuditSelectionContext";
import { ApiError, formatBackendError, shouldLinkToSettings } from "@/lib/errors";
import { StatusPill } from "@/lib/format";

const PAGE_SIZE = 50;
const LIVE_POLL_MS = 1000;
const ACTIVE_STATUSES = new Set(["pending", "running", "enriching", "crawling"]);

type SortBy = "url" | "status_code" | "word_count" | "response_time_ms";
type SortOrder = "asc" | "desc";

export default function PagesPage() {
  const { crawlRunId, ready, selectAudit, clearSelection } = useAuditSelection();
  const [selectedPageId, setSelectedPageId] = useState<number | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [sortBy, setSortBy] = useState<SortBy>("url");
  const [sortOrder, setSortOrder] = useState<SortOrder>("asc");
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<CrawledPage[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [runStatus, setRunStatus] = useState<string | null>(null);
  const [crawlProgress, setCrawlProgress] = useState<CrawlRunProgress | null>(null);

  useEffect(() => {
    const handle = window.setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, 300);
    return () => window.clearTimeout(handle);
  }, [searchInput]);

  useEffect(() => {
    setPage(1);
  }, [statusFilter, sortBy, sortOrder, crawlRunId]);

  // Single polling loop: each tick fetches both crawl status and the page
  // list, so the two can never race each other or leave loading stuck.
  useEffect(() => {
    if (!ready || !crawlRunId) return;
    let cancelled = false;
    let timer: number | null = null;
    let firstLoad = true;

    async function tick() {
      if (firstLoad) setLoading(true);
      try {
        const statusCode = statusFilter ? Number(statusFilter) : undefined;
        const [progress, res] = await Promise.all([
          apiClient.getCrawlRun(crawlRunId!),
          apiClient.getPages(crawlRunId!, {
            search: search || undefined,
            status_code: Number.isFinite(statusCode) ? statusCode : undefined,
            sort_by: sortBy,
            sort_order: sortOrder,
            page,
            page_size: PAGE_SIZE,
          }),
        ]);
        if (cancelled) return;
        setCrawlProgress(progress);
        setRunStatus(progress.status);
        setItems(res.items);
        setTotal(res.total);
        setError(null);
        setUnreachable(false);

        if (ACTIVE_STATUSES.has(progress.status)) {
          timer = window.setTimeout(() => void tick(), LIVE_POLL_MS);
        }
      } catch (err) {
        if (cancelled) return;

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
        if (firstLoad) {
          setItems([]);
          setTotal(0);
        }
        // Keep retrying so a transient failure doesn't permanently stop live updates.
        timer = window.setTimeout(() => void tick(), LIVE_POLL_MS);
      } finally {
        if (!cancelled) {
          setLoading(false);
          firstLoad = false;
        }
      }
    }

    void tick();
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [ready, crawlRunId, search, statusFilter, sortBy, sortOrder, page]);

  const columns = useMemo(
    () =>
      [
        { key: "url" as const, label: "URL / Title" },
        { key: "status_code" as const, label: "Status" },
        { key: "word_count" as const, label: "Words" },
        { key: "response_time_ms" as const, label: "Response" },
      ] as const,
    [],
  );

  function toggleSort(key: SortBy) {
    if (sortBy === key) {
      setSortOrder((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(key);
      setSortOrder(key === "url" ? "asc" : "desc");
    }
  }

  const targetTotal = crawlProgress?.max_pages ?? crawlProgress?.phase_total ?? null;
  const isRunActive = runStatus != null && ACTIVE_STATUSES.has(runStatus);

  return (
    <PageShell
      title="Pages"
      subtitle={crawlRunId ? `Crawled pages for run #${crawlRunId}` : "No audit selected."}
      crawlRunId={crawlRunId}
      ready={ready}
      loading={false}
      error={error}
      unreachable={unreachable}
    >
      <Card>
        <CardHeader className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle>
              {loading
                ? "Loading…"
                : isRunActive && targetTotal
                  ? `${total} / ${targetTotal} pages`
                  : `${total} page${total === 1 ? "" : "s"}`}
            </CardTitle>
            {runStatus ? (
              <div className="flex items-center gap-2">
                {isRunActive ? (
                  <span className="flex h-2 w-2 animate-pulse rounded-full bg-sky-500" />
                ) : null}
                <StatusPill
                  status={runStatus}
                  detail={
                    isRunActive && targetTotal
                      ? `${crawlProgress?.pages_crawled ?? total}/${targetTotal}`
                      : undefined
                  }
                />
              </div>
            ) : null}
          </div>
          <div className="grid gap-3 lg:grid-cols-12">
            <label className="space-y-1.5 text-sm lg:col-span-7">
              <span className="font-medium text-gray-700">Search URL</span>
              <input
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="Filter by URL substring…"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
              />
            </label>
            <label className="space-y-1.5 text-sm lg:col-span-3">
              <span className="font-medium text-gray-700">Status code</span>
              <input
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value.replace(/[^\d]/g, ""))}
                placeholder="e.g. 200"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
              />
            </label>
            <div className="flex items-end lg:col-span-2">
              <button
                type="button"
                onClick={() => {
                  setSearchInput("");
                  setSearch("");
                  setStatusFilter("");
                }}
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-semibold text-gray-800 hover:bg-gray-50"
              >
                Reset
              </button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {!loading && items.length === 0 && !error ? (
            <p className="px-6 py-10 text-sm text-gray-500">No pages match these filters.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="border-b border-gray-100 bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
                  <tr>
                    {columns.map((col) => {
                      const active = sortBy === col.key;
                      return (
                        <th key={col.key} className="px-6 py-3 font-medium">
                          <button
                            type="button"
                            onClick={() => toggleSort(col.key)}
                            className={`inline-flex items-center gap-1 hover:text-gray-800 ${
                              active ? "text-brand-700" : ""
                            }`}
                          >
                            {col.label}
                            <span className="tabular-nums text-[10px]">
                              {active ? (sortOrder === "asc" ? "▲" : "▼") : "↕"}
                            </span>
                          </button>
                        </th>
                      );
                    })}
                    <th className="px-6 py-3 font-medium">Issues</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((pageRow) => (
                    <tr
                      key={pageRow.id}
                      onClick={() => setSelectedPageId(pageRow.id)}
                      className="border-b border-gray-50 hover:bg-brand-50/40 cursor-pointer transition"
                    >
                      <td className="max-w-xl px-6 py-3">
                        <div className="truncate font-medium text-gray-900 group-hover:text-brand-700" title={pageRow.title ?? undefined}>
                          {pageRow.title || "Untitled"}
                        </div>
                        <div className="truncate text-xs text-gray-500" title={pageRow.url}>
                          {pageRow.url}
                        </div>
                      </td>
                      <td className="whitespace-nowrap px-6 py-3">
                        <StatusCode code={pageRow.status_code} />
                      </td>
                      <td className="whitespace-nowrap px-6 py-3 tabular-nums text-gray-700">
                        {pageRow.word_count ?? "—"}
                      </td>
                      <td className="whitespace-nowrap px-6 py-3 tabular-nums text-gray-700">
                        {pageRow.response_time_ms != null
                          ? `${Math.round(pageRow.response_time_ms)} ms`
                          : "—"}
                      </td>
                      <td className="whitespace-nowrap px-6 py-3 tabular-nums text-gray-700">
                        {pageRow.issue_count}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <PaginationBar page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
        </CardContent>
      </Card>

      {crawlRunId && (
        <PageDetailDrawer
          crawlRunId={crawlRunId}
          pageId={selectedPageId}
          onClose={() => setSelectedPageId(null)}
        />
      )}
    </PageShell>
  );
}

function StatusCode({ code }: { code: number | null }) {
  if (code == null) return <span className="text-gray-400">—</span>;
  const tone =
    code >= 200 && code < 300
      ? "bg-emerald-100 text-emerald-800"
      : code >= 300 && code < 400
        ? "bg-amber-100 text-amber-800"
        : "bg-red-100 text-red-800";
  return (
    <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold tabular-nums ${tone}`}>
      {code}
    </span>
  );
}
