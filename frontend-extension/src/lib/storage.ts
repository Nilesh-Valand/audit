/**
 * Persistence for the Chrome extension build.
 *
 * The extension page (chrome-extension://<id>/index.html) is a normal page
 * context, so plain localStorage works and keeps this file near-identical
 * to frontend-web/src/lib/storage.ts. Only the default API base URL differs:
 * the packaged extension ships pointed at the hosted backend by default.
 */

export const DEFAULT_API_BASE_URL = "https://seoaudit.theonetechnologies.co.in";
export const STORAGE_KEY_API_BASE = "apiBaseUrl";
export const STORAGE_KEY_SELECTED_PROJECT = "selectedProjectId";
export const STORAGE_KEY_SELECTED_RUN = "selectedCrawlRunId";

function readLocal(key: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeLocal(key: string, value: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* private mode / quota — ignore */
  }
}

function removeLocal(key: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}

export function getStoredApiBaseUrl(): string | null {
  const value = readLocal(STORAGE_KEY_API_BASE);
  if (typeof value === "string" && value.trim()) {
    return value.trim().replace(/\/$/, "");
  }
  return null;
}

export async function setApiBaseUrl(url: string): Promise<void> {
  const normalized = url.trim().replace(/\/$/, "");
  const current = getStoredApiBaseUrl();
  if (current !== normalized) {
    writeLocal(STORAGE_KEY_API_BASE, normalized);
    await clearSelectedAudit();
  }
}

export type SelectedAudit = {
  projectId: number | null;
  crawlRunId: number | null;
};

export async function getSelectedAudit(): Promise<SelectedAudit> {
  const projectRaw = readLocal(STORAGE_KEY_SELECTED_PROJECT);
  const runRaw = readLocal(STORAGE_KEY_SELECTED_RUN);
  const projectId = projectRaw != null ? Number(projectRaw) : NaN;
  const crawlRunId = runRaw != null ? Number(runRaw) : NaN;
  return {
    projectId: Number.isFinite(projectId) ? projectId : null,
    crawlRunId: Number.isFinite(crawlRunId) ? crawlRunId : null,
  };
}

export async function setSelectedAudit(selection: {
  projectId: number;
  crawlRunId: number;
}): Promise<void> {
  writeLocal(STORAGE_KEY_SELECTED_PROJECT, String(selection.projectId));
  writeLocal(STORAGE_KEY_SELECTED_RUN, String(selection.crawlRunId));
}

export async function clearSelectedAudit(): Promise<void> {
  removeLocal(STORAGE_KEY_SELECTED_PROJECT);
  removeLocal(STORAGE_KEY_SELECTED_RUN);
}
