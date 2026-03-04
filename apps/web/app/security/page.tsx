import Link from "next/link";

import { EntitySearchInput } from "@/components/entity-search-input";
import { TickerIcon } from "@/components/ticker-icon";
import { searchSecurities } from "@/lib/api";

type Props = {
  searchParams: Promise<{ q?: string }>;
};

export default async function SecuritySearchPage({ searchParams }: Props) {
  const query = (await searchParams).q?.trim() ?? "";
  let results = { query: "", rows: [] as Array<{ security_id: number; security_name: string | null; issuer_name: string | null; ticker: string | null; mic: string | null }> };
  let loadError = "";
  try {
    results = query ? await searchSecurities(query, 50) : results;
  } catch (error) {
    loadError = String(error);
  }

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-line/80 bg-card/80 p-6 shadow-panel">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-100">Security Search</h1>
        <p className="mt-2 text-sm text-slate-400">Search by ticker or issuer name.</p>
        <EntitySearchInput
          placeholder="AAPL or Apple"
          defaultValue={query}
          fallbackPath="/security"
          className="relative mt-4 max-w-2xl"
          inputClassName="min-w-[260px] w-full rounded-xl border border-line/80 bg-card/70 px-3 py-2 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-accentBlue/70"
          dropdownClassName="absolute left-0 right-0 top-[calc(100%+8px)] z-20 overflow-hidden rounded-xl border border-line/80 bg-[#02050c] shadow-panel"
        />
        <p className="mt-2 text-xs text-slate-500">Use ↑/↓ and Enter to navigate results.</p>
      </section>

      <section className="rounded-2xl border border-line/80 bg-card/80 p-5 shadow-panel">
        <h2 className="text-lg font-semibold text-slate-100">Results</h2>
        {loadError ? <p className="mt-2 text-sm text-rose-300">Search failed: {loadError}</p> : null}
        <div className="mt-4 overflow-x-auto rounded-xl border border-line/70">
          <table className="min-w-full divide-y divide-line/60 text-sm">
            <thead>
              <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-3 py-2">Ticker</th>
                <th className="px-3 py-2">Security</th>
                <th className="px-3 py-2">Issuer</th>
                <th className="px-3 py-2">MIC</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/50 text-slate-300">
              {results.rows.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-3 py-4 text-center text-sm text-slate-500">
                    No results.
                  </td>
                </tr>
              ) : (
                results.rows.map((row) => (
                  <tr key={row.security_id}>
                    <td className="px-3 py-2">
                      {row.ticker ? (
                        <Link
                          prefetch={false}
                          href={`/security/${encodeURIComponent(row.ticker)}`}
                          className="inline-flex items-center gap-2 text-accentBlue hover:text-white"
                        >
                          <TickerIcon ticker={row.ticker} label={row.security_name ?? row.issuer_name} />
                          <span>{row.ticker}</span>
                        </Link>
                      ) : (
                        "-"
                      )}
                    </td>
                    <td className="px-3 py-2">{row.security_name ?? "-"}</td>
                    <td className="px-3 py-2">{row.issuer_name ?? "-"}</td>
                    <td className="px-3 py-2">{row.mic ?? "-"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
