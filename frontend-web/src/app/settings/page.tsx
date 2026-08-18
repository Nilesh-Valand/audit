"use client";

import { FormEvent, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { apiClient } from "@/lib/api";
import { getApiBaseUrl } from "@/lib/config";
import { formatBackendError } from "@/lib/errors";
import { DEFAULT_API_BASE_URL, setApiBaseUrl } from "@/lib/storage";

export default function SettingsPage() {
  const [apiBase, setApiBase] = useState(DEFAULT_API_BASE_URL);
  const [saved, setSaved] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testMessage, setTestMessage] = useState<string | null>(null);
  const [testOk, setTestOk] = useState<boolean | null>(null);

  useEffect(() => {
    setApiBase(getApiBaseUrl());
  }, []);

  async function handleSave(event: FormEvent) {
    event.preventDefault();
    await setApiBaseUrl(apiBase);
    setSaved(true);
    window.setTimeout(() => setSaved(false), 2000);
  }

  async function handleTest() {
    setTesting(true);
    setTestMessage(null);
    setTestOk(null);
    try {
      await setApiBaseUrl(apiBase);
      const health = await apiClient.health();
      setTestOk(true);
      setTestMessage(`Connected. Backend status: ${health.status}`);
    } catch (error) {
      setTestOk(false);
      setTestMessage(formatBackendError(error));
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 lg:text-[1.75rem]">
          Settings
        </h1>
        <p className="mt-1.5 text-sm leading-relaxed text-slate-500">
          Configure the FastAPI backend URL used by this app.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Backend connection</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSave} className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-700">API base URL</label>
              <input
                className="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
                value={apiBase}
                onChange={(event) => setApiBase(event.target.value)}
                placeholder={DEFAULT_API_BASE_URL}
              />
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <button
                type="submit"
                className="rounded-xl bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-brand-700"
              >
                Save
              </button>
              <button
                type="button"
                onClick={() => void handleTest()}
                disabled={testing}
                className="rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-60"
              >
                {testing ? "Testing…" : "Test Connection"}
              </button>
              {saved ? <span className="text-sm text-emerald-700">Saved</span> : null}
            </div>

            {testMessage ? (
              <div
                className={`rounded-lg px-4 py-3 text-sm ${
                  testOk ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-700"
                }`}
              >
                {testMessage}
              </div>
            ) : null}
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Environment default</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-gray-600">
          You can also set the backend URL via the{" "}
          <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-800">
            NEXT_PUBLIC_API_BASE_URL
          </code>{" "}
          environment variable. A saved value above overrides that default.
        </CardContent>
      </Card>
    </div>
  );
}
