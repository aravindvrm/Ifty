"use client";

import { useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

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
    <div className="card">
      <h3>Job Controls</h3>
      <div className="input-row">
        <button disabled={!!busy} onClick={() => run("Resolve Mappings", "/jobs/resolve-mappings?limit=0")}>
          Resolve Mappings
        </button>
        <button disabled={!!busy} onClick={() => run("Refresh Aggregates", "/jobs/refresh-aggregates")}>
          Refresh Aggregates
        </button>
        <button disabled={!!busy} onClick={() => run("Refresh Universe", "/jobs/refresh-universe?top_n=300")}>
          Refresh Universe
        </button>
      </div>
      <p className="page-subtitle">{status || "No job run yet."}</p>
    </div>
  );
}
