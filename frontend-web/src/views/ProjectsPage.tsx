"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { BackendUnreachable } from "@/components/BackendUnreachable";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { apiClient, type CrawlRun, type Project } from "@/lib/api";
import { useAuditSelection } from "@/lib/AuditSelectionContext";
import { formatBackendError, shouldLinkToSettings } from "@/lib/errors";
import { formatDate, formatScore, StatusPill } from "@/lib/format";

type ProjectRow = {
  project: Project;
  latestRun: CrawlRun | null;
  overallScore: number | null;
};

export default function ProjectsPage() {
  const params = useParams();
  const raw = params?.projectId;
  const projectIdParam = Array.isArray(raw) ? raw[0] : raw;
  const selectedProjectId = projectIdParam ? Number(projectIdParam) : null;

  if (selectedProjectId && Number.isFinite(selectedProjectId)) {
    return <ProjectDetailView projectId={selectedProjectId} />;
  }

  return <ProjectsListView />;
}

function ProjectsListView() {
  const { clearProjectIfMatching } = useAuditSelection();
  const [rows, setRows] = useState<ProjectRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setUnreachable(false);
    try {
      // Single request — backend embeds latest run status + overall score.
      const projects = await apiClient.listProjects({ page: 1, page_size: 100 });
      setRows(
        projects.items.map((project) => ({
          project,
          latestRun: project.latest_run_id
            ? {
                id: project.latest_run_id,
                project_id: project.id,
                status: project.latest_run_status ?? "unknown",
                total_pages: 0,
                started_at: project.latest_run_started_at ?? null,
                finished_at: project.latest_run_finished_at ?? null,
              }
            : null,
          overallScore: project.overall_score ?? null,
        })),
      );
    } catch (err) {
      setUnreachable(shouldLinkToSettings(err));
      setError(formatBackendError(err));
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function deleteProject(project: Project) {
    const ok = window.confirm(
      `Delete project “${project.domain}” and all of its crawl runs? This cannot be undone.`,
    );
    if (!ok) return;

    setDeletingId(project.id);
    setError(null);
    try {
      await apiClient.deleteProject(project.id);
      await clearProjectIfMatching(project.id);
      setRows((prev) => prev.filter((row) => row.project.id !== project.id));
    } catch (err) {
      setUnreachable(shouldLinkToSettings(err));
      setError(formatBackendError(err));
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900 lg:text-[1.75rem]">
            Projects
          </h1>
          <p className="mt-1.5 text-sm leading-relaxed text-slate-500">
            Audited domains with latest crawl status and overall score.
          </p>
        </div>
        <Link
          href="/audits/new"
          className="shrink-0 rounded-xl bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-brand-700"
        >
          New Audit
        </Link>
      </div>

      {unreachable && error ? <BackendUnreachable message={error} /> : null}
      {!unreachable && error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-800">
          {error}
        </div>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>All projects</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <p className="px-6 py-8 text-sm text-gray-500">Loading projects…</p>
          ) : rows.length === 0 && !error ? (
            <div className="px-6 py-8 text-sm text-gray-500">
              No projects yet.{" "}
              <Link href="/audits/new" className="font-semibold text-brand-700 hover:underline">
                Start a new audit
              </Link>
              .
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="border-b border-gray-100 bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
                  <tr>
                    <th className="px-6 py-3 font-medium">Domain</th>
                    <th className="px-6 py-3 font-medium">Latest status</th>
                    <th className="px-6 py-3 font-medium">Score</th>
                    <th className="px-6 py-3 font-medium">Last crawl</th>
                    <th className="px-6 py-3 font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map(({ project, latestRun, overallScore }, index) => (
                    <tr key={project.id} className="border-b border-gray-50 last:border-0">
                      <td className="px-6 py-4">
                        <Link
                          href={`/projects/${project.id}`}
                          className="font-semibold text-brand-700 hover:underline"
                        >
                          {project.domain}
                        </Link>
                        <div className="mt-0.5 text-xs text-gray-400">#{index + 1}</div>
                      </td>
                      <td className="px-6 py-4">
                        {latestRun ? <StatusPill status={latestRun.status} /> : "—"}
                      </td>
                      <td className="px-6 py-4 font-semibold text-gray-900">
                        {formatScore(overallScore)}
                      </td>
                      <td className="px-6 py-4 text-gray-600">
                        {formatDate(latestRun?.finished_at ?? latestRun?.started_at)}
                      </td>
                      <td className="px-6 py-4 text-right">
                        <button
                          type="button"
                          disabled={deletingId === project.id}
                          onClick={() => void deleteProject(project)}
                          className="rounded-lg border border-red-200 bg-white px-3 py-1.5 text-xs font-semibold text-red-700 hover:bg-red-50 disabled:opacity-60"
                        >
                          {deletingId === project.id ? "Deleting…" : "Delete"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function ProjectDetailView({ projectId }: { projectId: number }) {
  const router = useRouter();
  const {
    selectAudit,
    crawlRunId: selectedRunId,
    clearProjectIfMatching,
    clearRunIfMatching,
  } = useAuditSelection();

  const [project, setProject] = useState<Project | null>(null);
  const [runs, setRuns] = useState<(CrawlRun & { overallScore: number | null })[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [unreachable, setUnreachable] = useState(false);
  const [openingId, setOpeningId] = useState<number | null>(null);
  const [deletingRunId, setDeletingRunId] = useState<number | null>(null);
  const [deletingProject, setDeletingProject] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setUnreachable(false);
    try {
      const [projects, crawlRuns] = await Promise.all([
        apiClient.listProjects({ page: 1, page_size: 200 }),
        apiClient.listCrawlRuns({ project_id: projectId, page: 1, page_size: 100 }),
      ]);

      const found = projects.items.find((p) => p.id === projectId) ?? null;
      setProject(found);

      // Cap concurrent summary fetches so a slow/busy backend can't stall the page.
      const withScores: (CrawlRun & { overallScore: number | null })[] = [];
      const batchSize = 4;
      for (let i = 0; i < crawlRuns.items.length; i += batchSize) {
        const batch = crawlRuns.items.slice(i, i + batchSize);
        const scored = await Promise.all(
          batch.map(async (run) => {
            let overallScore: number | null = null;
            if (run.status === "completed") {
              try {
                const summary = await apiClient.getSummary(run.id);
                overallScore = summary.overall_score;
              } catch {
                overallScore = null;
              }
            }
            return { ...run, overallScore };
          }),
        );
        withScores.push(...scored);
      }
      setRuns(withScores);
    } catch (err) {
      setUnreachable(shouldLinkToSettings(err));
      setError(formatBackendError(err));
      setRuns([]);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function openRun(run: CrawlRun) {
    setOpeningId(run.id);
    setError(null);
    try {
      await selectAudit(projectId, run.id);
      router.push("/");
    } catch (err) {
      setUnreachable(shouldLinkToSettings(err));
      setError(formatBackendError(err));
    } finally {
      setOpeningId(null);
    }
  }

  async function deleteRun(run: CrawlRun) {
    const ok = window.confirm(
      `Delete this crawl run? Issues, pages, and scores for this run will be removed.`,
    );
    if (!ok) return;

    setDeletingRunId(run.id);
    setError(null);
    try {
      await apiClient.deleteCrawlRun(run.id);
      await clearRunIfMatching(run.id);
      setRuns((prev) => prev.filter((r) => r.id !== run.id));
    } catch (err) {
      setUnreachable(shouldLinkToSettings(err));
      setError(formatBackendError(err));
    } finally {
      setDeletingRunId(null);
    }
  }

  async function deleteProject() {
    const label = project?.domain ?? `project #${projectId}`;
    const ok = window.confirm(
      `Delete ${label} and all of its crawl runs? This cannot be undone.`,
    );
    if (!ok) return;

    setDeletingProject(true);
    setError(null);
    try {
      await apiClient.deleteProject(projectId);
      await clearProjectIfMatching(projectId);
      router.push("/projects");
    } catch (err) {
      setUnreachable(shouldLinkToSettings(err));
      setError(formatBackendError(err));
      setDeletingProject(false);
    }
  }

  const busy = deletingProject || deletingRunId !== null || openingId !== null;

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link href="/projects" className="text-sm font-medium text-brand-700 hover:underline">
            ← All projects
          </Link>
          <h1 className="mt-2 text-3xl font-bold text-gray-900">
            {project?.domain ?? `Project #${projectId}`}
          </h1>
          <p className="mt-1 text-sm text-gray-500">Crawl run history for this project.</p>
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={() => void deleteProject()}
          className="rounded-lg border border-red-200 bg-white px-4 py-2.5 text-sm font-semibold text-red-700 hover:bg-red-50 disabled:opacity-60"
        >
          {deletingProject ? "Deleting…" : "Delete project"}
        </button>
      </div>

      {unreachable && error ? <BackendUnreachable message={error} /> : null}
      {!unreachable && error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-800">
          {error}
        </div>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Crawl runs</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <p className="px-6 py-8 text-sm text-gray-500">Loading runs…</p>
          ) : runs.length === 0 && !error ? (
            <div className="px-6 py-8 text-sm text-gray-500">
              No crawl runs yet.{" "}
              <Link href="/audits/new" className="font-semibold text-brand-700 hover:underline">
                Start an audit
              </Link>
              .
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="border-b border-gray-100 bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
                  <tr>
                    <th className="px-6 py-3 font-medium">Run</th>
                    <th className="px-6 py-3 font-medium">Status</th>
                    <th className="px-6 py-3 font-medium">Pages</th>
                    <th className="px-6 py-3 font-medium">Score</th>
                    <th className="px-6 py-3 font-medium">Finished</th>
                    <th className="px-6 py-3 font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run, index) => {
                    const isSelected = selectedRunId === run.id;
                    return (
                      <tr
                        key={run.id}
                        className={`border-b border-gray-50 last:border-0 ${
                          isSelected ? "bg-brand-50/60" : ""
                        }`}
                      >
                        <td className="px-6 py-4 font-medium text-gray-900">#{index + 1}</td>
                        <td className="px-6 py-4">
                          <StatusPill status={run.status} />
                        </td>
                        <td className="px-6 py-4 text-gray-600">{run.total_pages}</td>
                        <td className="px-6 py-4 font-semibold text-gray-900">
                          {formatScore(run.overallScore)}
                        </td>
                        <td className="px-6 py-4 text-gray-600">
                          {formatDate(run.finished_at ?? run.started_at)}
                        </td>
                        <td className="px-6 py-4">
                          <div className="flex justify-end gap-2">
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void openRun(run)}
                              className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-800 hover:bg-gray-50 disabled:opacity-60"
                            >
                              {openingId === run.id ? "Opening…" : "Open"}
                            </button>
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void deleteRun(run)}
                              className="rounded-lg border border-red-200 bg-white px-3 py-1.5 text-xs font-semibold text-red-700 hover:bg-red-50 disabled:opacity-60"
                            >
                              {deletingRunId === run.id ? "Deleting…" : "Delete"}
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <p className="text-xs text-gray-500">
        Opening a run sets it as the active audit for Dashboard, Issues, Pages, and Report.
        Deleting clears that selection if it was the active audit.
      </p>
    </div>
  );
}
