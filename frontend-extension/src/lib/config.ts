import { DEFAULT_API_BASE_URL, getStoredApiBaseUrl } from "./storage";

/**
 * Resolve FastAPI base URL.
 * Preference order: localStorage override → VITE_API_BASE_URL (build-time) → hosted default.
 */
export function getApiBaseUrl(): string {
  const stored = getStoredApiBaseUrl();
  if (stored) return stored;

  const value = import.meta.env.VITE_API_BASE_URL;
  if (typeof value === "string" && value.trim()) {
    return value.trim().replace(/\/$/, "");
  }
  return DEFAULT_API_BASE_URL;
}
