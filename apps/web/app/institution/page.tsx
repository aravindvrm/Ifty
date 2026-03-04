import Link from "next/link";

import { EntitySearchInput } from "@/components/entity-search-input";
import { getInstitutionUniverse } from "@/lib/api";
import { fmtNumber } from "@/lib/format";

type Props = {
  searchParams: Promise<{ q?: string }>;
};

export default async function InstitutionDirectoryPage({ searchParams }: Props) {
  const q = ((await searchParams).q ?? "").trim().toLowerCase();

  let universe;
  try {
    universe = await getInstitutionUniverse(500);
  } catch (error) {
    return (
      <section className="rounded-2xl border border-line/80 bg-card/80 p-6 shadow-panel">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-100">Institutions</h1>
        <p className="mt-2 text-sm text-slate-400">Failed to load institution universe.</p>
        <pre className="mt-3 overflow-auto rounded-xl border border-line/70 bg-black/35 p-3 text-xs text-rose-200">
          {String(error)}
        </pre>
      </section>
    );
  }

  const rows = q
    ? universe.rows.filter((row) => {
        const name = (row.manager_name ?? "").toLowerCase();
        const cik = (row.cik ?? "").toLowerCase();
        return name.includes(q) || cik.includes(q);
      })
    : universe.rows;

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-line/80 bg-card/80 p-6 shadow-panel">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-100">Institution Directory</h1>
        <p className="mt-2 text-sm text-slate-400">Open any tracked institution by rank, name, or CIK.</p>
        <EntitySearchInput
          placeholder="Search institution or CIK"
          defaultValue={q}
          fallbackPath="/institution"
          className="relative mt-4 max-w-2xl"
          inputClassName="min-w-[280px] w-full rounded-xl border border-line/80 bg-card/70 px-3 py-2 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-accentBlue/70"
          dropdownClassName="absolute left-0 right-0 top-[calc(100%+8px)] z-20 overflow-hidden rounded-xl border border-line/80 bg-[#02050c] shadow-panel"
        />
        <p className="mt-2 text-xs text-slate-500">Use ↑/↓ and Enter to navigate results.</p>
      </section>

      <section className="rounded-2xl border border-line/80 bg-card/80 p-5 shadow-panel">
        <h2 className="text-lg font-semibold text-slate-100">Tracked Universe</h2>
        <div className="mt-4 overflow-x-auto rounded-xl border border-line/70">
          <table className="min-w-full divide-y divide-line/60 text-sm">
            <thead>
              <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-3 py-2">Rank</th>
                <th className="px-3 py-2">Institution</th>
                <th className="px-3 py-2">CIK</th>
                <th className="px-3 py-2 text-right">Total Value (USD)</th>
                <th className="px-3 py-2">As Of</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/50 text-slate-300">
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-3 py-4 text-center text-sm text-slate-500">
                    No institutions match your query.
                  </td>
                </tr>
              ) : (
                rows.map((row) => (
                  <tr key={row.manager_id}>
                    <td className="px-3 py-2">{row.rank}</td>
                    <td className="px-3 py-2">
                      <Link
                        prefetch={false}
                        href={`/institution/${encodeURIComponent(String(row.manager_id))}`}
                        className="text-accentBlue hover:text-white"
                      >
                        {row.manager_name}
                      </Link>
                    </td>
                    <td className="px-3 py-2">{row.cik ?? "-"}</td>
                    <td className="px-3 py-2 text-right">{fmtNumber(row.total_value_usd ?? 0, 0)}</td>
                    <td className="px-3 py-2">{row.as_of_report_date}</td>
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
