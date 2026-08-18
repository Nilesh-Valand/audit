"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { BackendUnreachable } from "@/components/BackendUnreachable";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { apiClient, type CrawledPage, type CrawlRunProgress, type Project } from "@/lib/api";
import { useAuditSelection } from "@/lib/AuditSelectionContext";
import {
  formatBackendError,
  isTimeoutError,
  shouldLinkToSettings,
} from "@/lib/errors";
import { normalizeUrl, ProgressBar, StatusPill } from "@/lib/format";

const POLL_MS = 1000;
/** Soft poll failures (timeouts while job is still running) before we warn. */
const MAX_SOFT_FAILURES = 8;
/** Hard failures (backend down) before we stop — ~2+ minutes with backoff. */
const MAX_HARD_FAILURES = 5;
const FATAL_FAILURE_WINDOW_MS = 120_000;
/** Treat pending/running without an active worker as dead after this many polls. */
const ORPHAN_CONFIRM_POLLS = 2;

function domainFromUrl(url: string): string {
  try {
    return new URL(normalizeUrl(url)).hostname.toLowerCase();
  } catch {
    return url.trim().toLowerCase();
  }
}

async function findOrCreateProject(startUrl: string): Promise<Project> {
  const domain = domainFromUrl(startUrl);
  const existing = await apiClient.listProjects({ page: 1, page_size: 200 });
  const match = existing.items.find((p) => p.domain.toLowerCase() === domain);
  if (match) return match;
  return apiClient.createProject(domain);
}

function progressCopy(progress: CrawlRunProgress | null, pagesCrawled: number, maxPages: number): string {
  if (!progress) return "Starting…";
  if (progress.status === "failed") {
    return progress.error_message || "Crawl failed.";
  }
  if (progress.status === "completed") {
    return "Complete — opening dashboard…";
  }
  const label = progress.phase_label;
  const cur = progress.phase_current;
  const tot = progress.phase_total;
  if (label && cur != null && tot != null && tot > 0) {
    return `${label}: ${cur} / ${tot}`;
  }
  if (label) return `${label}…`;
  if (progress.status === "enriching" || pagesCrawled >= maxPages) {
    return "Running checks & scoring…";
  }
  if (progress.status === "pending") return "Queued — waiting for crawl worker…";
  return "Crawl in progress";
}

export default function NewAuditPage() {
  const router = useRouter();
  const { selectAudit } = useAuditSelection();

  const [startUrl, setStartUrl] = useState("");
  const [maxPages, setMaxPages] = useState(50);
  const [enablePagespeed, setEnablePagespeed] = useState(false);

  const [submitting, setSubmitting] = useState(false);
  const [polling, setPolling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unreachable, setUnreachable] = useState(false);

  const [crawlRunId, setCrawlRunId] = useState<number | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [pagesCrawled, setPagesCrawled] = useState(0);
  const [activeMaxPages, setActiveMaxPages] = useState(50);
  const [latestProgress, setLatestProgress] = useState<CrawlRunProgress | null>(null);
  const [recentPages, setRecentPages] = useState<CrawledPage[]>([]);

  /** Bumps on stop/start so in-flight polls and Strict Mode cleanups cannot poison a new run. */
  const pollGenerationRef = useRef(0);
  const pollTimerRef = useRef<number | null>(null);
  const softFailuresRef = useRef(0);
  const hardFailuresRef = useRef(0);
  const firstFailureAtRef = useRef<number | null>(null);
  const orphanStreakRef = useRef(0);

  useEffect(() => {
    return () => {
      pollGenerationRef.current += 1;
      if (pollTimerRef.current !== null) {
        window.clearTimeout(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, []);

  function clearPollTimer() {
    if (pollTimerRef.current !== null) {
      window.clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }

  function stopPolling() {
    pollGenerationRef.current += 1;
    clearPollTimer();
    setPolling(false);
  }

  function resetFailureCounters() {
    softFailuresRef.current = 0;
    hardFailuresRef.current = 0;
    firstFailureAtRef.current = null;
  }

  function resetUiForNewSubmit() {
    setCrawlRunId(null);
    setLatestProgress(null);
    setPagesCrawled(0);
    setRecentPages([]);
    setStatus("pending");
    setError(null);
    setUnreachable(false);
  }

  function handleCancel() {
    stopPolling();
    setSubmitting(false);
    setError("Audit cancelled. You can start a new one when ready.");
  }

  function startPolling(runId: number, projId: number) {
    const generation = ++pollGenerationRef.current;
    clearPollTimer();
    setPolling(true);
    resetFailureCounters();
    orphanStreakRef.current = 0;
    setUnreachable(false);
    setError(null);

    const scheduleNext = () => {
      if (pollGenerationRef.current !== generation) return;
      pollTimerRef.current = window.setTimeout(() => {
        void tick();
      }, POLL_MS);
    };

    const finishWithError = (message: string, linkSettings: boolean) => {
      if (pollGenerationRef.current !== generation) return;
      stopPolling();
      setSubmitting(false);
      setUnreachable(linkSettings);
      setError(message);
    };

    const handlePollError = (err: unknown) => {
      if (pollGenerationRef.current !== generation) return;

      const now = Date.now();
      if (firstFailureAtRef.current == null) {
        firstFailureAtRef.current = now;
      }

      const timedOut = isTimeoutError(err);
      if (timedOut) {
        softFailuresRef.current += 1;
        if (softFailuresRef.current < MAX_SOFT_FAILURES) {
          scheduleNext();
          return;
        }
      } else {
        hardFailuresRef.current += 1;
        if (hardFailuresRef.current < MAX_HARD_FAILURES) {
          scheduleNext();
          return;
        }
      }

      const elapsed = now - (firstFailureAtRef.current ?? now);
      if (elapsed < FATAL_FAILURE_WINDOW_MS && hardFailuresRef.current < MAX_HARD_FAILURES) {
        scheduleNext();
        return;
      }

      finishWithError(formatBackendError(err), shouldLinkToSettings(err));
    };

    async function tick() {
      if (pollGenerationRef.current !== generation) return;

      try {
        const progress = await apiClient.getCrawlRun(runId);
        if (pollGenerationRef.current !== generation) return;

        resetFailureCounters();

        setUnreachable(false);
        setError(null);
        setLatestProgress(progress);
        setStatus(progress.status);
        setPagesCrawled(progress.pages_crawled);

        // Best-effort live page list — a failure here shouldn't affect progress polling.
        try {
          const pages = await apiClient.getPages(runId, {
            sort_by: "id",
            sort_order: "desc",
            page: 1,
            page_size: 20,
          });
          if (pollGenerationRef.current === generation) {
            setRecentPages(pages.items);
          }
        } catch {
          /* ignore — live list is a nice-to-have */
        }

        const terminal =
          progress.status === "completed" || progress.status === "failed";
        const looksOrphaned =
          !progress.active &&
          (progress.status === "pending" ||
            progress.status === "running" ||
            progress.status === "enriching");

        if (looksOrphaned) {
          orphanStreakRef.current += 1;
        } else {
          orphanStreakRef.current = 0;
        }

        const orphaned = looksOrphaned && orphanStreakRef.current >= ORPHAN_CONFIRM_POLLS;

        if (!terminal && !orphaned) {
          scheduleNext();
          return;
        }

        // Stop the timer without bumping generation yet — stopPolling() would
        // invalidate this completion path and skip the dashboard redirect.
        clearPollTimer();
        setPolling(false);
        setSubmitting(false);

        if (progress.status === "failed" || orphaned) {
          pollGenerationRef.current += 1;
          setError(
            progress.error_message ||
              "Crawl failed. Check the backend terminal for the error, then try again.",
          );
          return;
        }

        await selectAudit(projId, runId);
        // Skip navigate only if the user cancelled or started another audit mid-finish.
        if (pollGenerationRef.current !== generation) return;
        pollGenerationRef.current += 1;
        router.replace("/");
      } catch (err) {
        handlePollError(err);
      }
    }

    void tick();
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    stopPolling();
    resetUiForNewSubmit();

    const url = normalizeUrl(startUrl);
    if (!url) {
      setError("Enter a domain or start URL.");
      return;
    }

    try {
      const parsed = new URL(url);
      if (!parsed.hostname) {
        setError("Enter a valid URL (e.g. https://example.com).");
        return;
      }
    } catch {
      setError("Enter a valid URL (e.g. https://example.com).");
      return;
    }

    const max = Math.floor(maxPages) || 1;
    if (max > 5000) {
      setError("Maximum allowed pages is 5,000. Please enter 5,000 or fewer.");
      return;
    }
    if (max < 1) {
      setError("Max pages must be at least 1.");
      return;
    }
    setActiveMaxPages(max);
    setSubmitting(true);

    try {
      const project = await findOrCreateProject(url);
      const created = await apiClient.createCrawlRun({
        project_id: project.id,
        start_url: url,
        max_pages: max,
        enable_pagespeed: enablePagespeed,
      });

      setCrawlRunId(created.crawl_run_id);
      // Point the shared selection at this run immediately (not just on completion)
      // so Pages/Issues/Report can show live progress while the crawl is still running.
      await selectAudit(project.id, created.crawl_run_id);
      startPolling(created.crawl_run_id, project.id);
    } catch (err) {
      setSubmitting(false);
      setUnreachable(shouldLinkToSettings(err));
      setError(formatBackendError(err));
    }
  }

  const phaseCur = latestProgress?.phase_current;
  const phaseTot = latestProgress?.phase_total;
  const showPhaseBar =
    latestProgress?.phase != null &&
    latestProgress.phase !== "crawling" &&
    phaseCur != null &&
    phaseTot != null &&
    phaseTot > 0;

  const crawlPct =
    activeMaxPages > 0 ? Math.min(100, (pagesCrawled / activeMaxPages) * 100) : 0;
  const phasePct =
    showPhaseBar && phaseTot ? Math.min(100, (phaseCur / phaseTot) * 100) : 0;

  const busy = submitting || polling;

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 lg:text-[1.75rem]">New Audit</h1>
        <p className="mt-1.5 text-sm leading-relaxed text-slate-500">
          Start a crawl against a domain. Progress updates while the backend runs.
        </p>
      </div>

      {unreachable && error ? <BackendUnreachable message={error} /> : null}
      {!unreachable && error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-800">
          {error}
        </div>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Crawl settings</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={(e) => void handleSubmit(e)} className="space-y-5">
            <div className="space-y-2">
              <label className="text-sm font-medium text-gray-700" htmlFor="start-url">
                Domain / start URL
              </label>
              <input
                id="start-url"
                className="w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
                value={startUrl}
                onChange={(e) => setStartUrl(e.target.value)}
                placeholder="https://example.com"
                disabled={busy}
                required
              />
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium text-gray-700" htmlFor="max-pages">
                  Max pages
                </label>
                <span className="text-xs font-semibold text-brand-700 bg-brand-50 px-2 py-0.5 rounded-md border border-brand-100">
                  Max: 5,000 pages
                </span>
              </div>
              <input
                id="max-pages"
                type="number"
                min={1}
                max={5000}
                className={`w-full rounded-lg border px-3 py-2.5 text-sm outline-none transition ${
                  maxPages > 5000
                    ? "border-red-400 focus:border-red-500 focus:ring-2 focus:ring-red-100"
                    : "border-gray-300 focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
                }`}
                value={maxPages}
                onChange={(e) => setMaxPages(Number(e.target.value))}
                disabled={busy}
              />
              {maxPages > 5000 ? (
                <p className="text-xs font-semibold text-red-600">
                  Maximum allowed pages is 5,000.
                </p>
              ) : (
                <p className="text-xs text-gray-500">
                  Enter up to 5,000 pages to crawl for this audit.
                </p>
              )}
            </div>

            <label className="flex items-start gap-3 rounded-lg border border-gray-200 px-4 py-3">
              <input
                type="checkbox"
                className="mt-1 h-4 w-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500"
                checked={enablePagespeed}
                onChange={(e) => setEnablePagespeed(e.target.checked)}
                disabled={busy}
              />
              <span>
                <span className="block text-sm font-medium text-gray-900">
                  PageSpeed enrichment
                </span>
                <span className="mt-0.5 block text-xs text-gray-500">
                  Off by default. Requires a PageSpeed API key on the backend when enabled.
                  On large crawls this step can take several minutes.
                </span>
              </span>
            </label>

            <div className="flex flex-wrap items-center gap-3">
              <button
                type="submit"
                disabled={busy}
                className="rounded-xl bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-brand-700 disabled:opacity-60"
              >
                {polling ? "Auditing…" : submitting ? "Starting…" : "Start audit"}
              </button>
              {busy ? (
                <button
                  type="button"
                  onClick={handleCancel}
                  className="rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50"
                >
                  Cancel
                </button>
              ) : null}
            </div>
          </form>
        </CardContent>
      </Card>

      {(polling || crawlRunId !== null) && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <CardTitle>Audit progress</CardTitle>
              {status ? <StatusPill status={status} /> : null}
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <ProgressBar
              value={crawlPct}
              label={`${pagesCrawled} / ${activeMaxPages} pages crawled`}
            />
            {showPhaseBar ? (
              <ProgressBar
                value={phasePct}
                label={progressCopy(latestProgress, pagesCrawled, activeMaxPages)}
              />
            ) : (
              <p className="text-xs text-gray-500">
                {progressCopy(latestProgress, pagesCrawled, activeMaxPages)}
              </p>
            )}
            {!polling && status === "failed" ? (
              <p className="text-sm text-red-700">
                This crawl failed. You can start a new one or check{" "}
                <Link href="/projects" className="font-semibold text-brand-700 hover:underline">
                  Projects
                </Link>
                .
              </p>
            ) : null}

            {recentPages.length > 0 ? (
              <div className="space-y-2">
                <p className="text-xs font-medium uppercase tracking-wide text-gray-500">
                  Recently crawled
                </p>
                <div className="max-h-72 overflow-y-auto rounded-lg border border-gray-100">
                  <table className="min-w-full text-left text-sm">
                    <tbody>
                      {recentPages.map((pageRow) => (
                        <tr key={pageRow.id} className="border-b border-gray-50 last:border-b-0">
                          <td className="truncate px-3 py-2 text-gray-700" title={pageRow.url}>
                            {pageRow.url}
                          </td>
                          <td className="w-16 whitespace-nowrap px-3 py-2 text-right tabular-nums text-xs text-gray-500">
                            {pageRow.status_code ?? "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
