"use client";

import { useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

async function postJob(path: string) {
  const res = await fetch(`${API_BASE}${path}`, { method: "POST" });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return text ? JSON.parse(text) : {};
}

export function OpsControls() {
  const [busy, setBusy] = useState<string>("");
  const [status, setStatus] = useState<string>("");

  async function run(label: string, path: string) {
    try {
      setBusy(label);
      setStatus(`${label}: running...`);
      const body = await postJob(path);
      setStatus(`${label}: done (${JSON.stringify(body)})`);
    } catch (error) {
      setStatus(`${label}: failed (${String(error)})`);
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="rounded-2xl border border-line/80 bg-card/80 p-5 shadow-panel">
      <h3 className="text-lg font-semibold text-slate-100">Job Controls</h3>
      <div className="mt-4 flex flex-wrap gap-2">
        <button
          disabled={!!busy}
          onClick={() => run("Resolve Mappings", "/jobs/resolve-mappings?limit=0")}
          className="rounded-xl border border-line/80 bg-cardSoft/80 px-3 py-2 text-sm text-slate-200 transition hover:border-accentBlue/70 hover:text-white disabled:opacity-40"
        >
          Resolve Mappings
        </button>
        <button
          disabled={!!busy}
          onClick={() => run("Refresh Aggregates", "/jobs/refresh-aggregates")}
          className="rounded-xl border border-line/80 bg-cardSoft/80 px-3 py-2 text-sm text-slate-200 transition hover:border-accentBlue/70 hover:text-white disabled:opacity-40"
        >
          Refresh Aggregates
        </button>
        <button
          disabled={!!busy}
          onClick={() => run("Refresh Universe", "/jobs/refresh-universe?top_n=300")}
          className="rounded-xl border border-line/80 bg-cardSoft/80 px-3 py-2 text-sm text-slate-200 transition hover:border-accentBlue/70 hover:text-white disabled:opacity-40"
        >
          Refresh Universe
        </button>
      </div>
      <p className="mt-3 text-sm text-slate-400">{status || "No job run yet."}</p>
    </section>
  );
}
