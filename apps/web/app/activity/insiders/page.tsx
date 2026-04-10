import { InsiderLiveTable } from "@/components/insider-live-table";
import { getInsiderFeed } from "@/lib/api";

export default async function ActivityInsidersPage() {
  let loadError: string | null = null;
  const primary = await getInsiderFeed({
    days: 90,
    limitN: 2000,
  }).catch((error) => {
    loadError = String(error);
    return null;
  });

  return (
    <div className="space-y-6">
      <section className="rounded-none p-6 shadow-panel">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-100">Insider Activity</h1>
        <p className="mt-2 text-sm text-slate-400">
          Search and filter Form 4 transactions by signal, role group, and date window.
        </p>
      </section>

      <section>
        <InsiderLiveTable rows={primary?.rows ?? []} loadError={loadError} />
      </section>
    </div>
  );
}
