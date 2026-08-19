import { Link } from "react-router-dom";

export function BackendUnreachable({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-950">
      <p className="font-medium">{message}</p>
      <div className="mt-3 flex items-center gap-4">
        <Link to="/settings" className="font-semibold text-brand-700 hover:underline">
          Open Settings →
        </Link>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="font-semibold text-amber-900 underline hover:text-amber-950"
        >
          Retry Connection
        </button>
      </div>
    </div>
  );
}
