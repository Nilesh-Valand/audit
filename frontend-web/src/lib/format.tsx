export function ProgressBar({
  value,
  label,
}: {
  value: number;
  label?: string;
}) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <div className="space-y-2">
      {label ? <div className="text-sm text-gray-600">{label}</div> : null}
      <div className="h-2.5 overflow-hidden rounded-full bg-gray-100">
        <div
          className="h-full rounded-full bg-brand-600 transition-all duration-300"
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  );
}

export function StatusPill({
  status,
  detail,
}: {
  status: string;
  detail?: string | number | null;
}) {
  const key = status.toLowerCase();
  const className =
    key === "completed"
      ? "bg-emerald-50 text-emerald-700 ring-emerald-100"
      : key === "failed"
        ? "bg-red-50 text-red-700 ring-red-100"
        : key === "running" || key === "enriching" || key === "crawling"
          ? "bg-sky-50 text-sky-700 ring-sky-100"
          : "bg-amber-50 text-amber-700 ring-amber-100";

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold capitalize ring-1 ring-inset ${className}`}
    >
      <span>{status.replace(/_/g, " ")}</span>
      {detail != null && String(detail).trim() !== "" ? (
        <span className="font-mono text-[11px] opacity-90">({detail})</span>
      ) : null}
    </span>
  );
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatScore(score: number | null | undefined): string {
  if (score === null || score === undefined) return "—";
  return String(Math.round(score));
}

export function normalizeUrl(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return trimmed;
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  return `https://${trimmed}`;
}
