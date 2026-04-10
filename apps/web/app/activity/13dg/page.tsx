import { FeedLiveTable } from "@/components/feed-live-table";
import { get13DGFeed } from "@/lib/api";

export default async function Activity13DGPage() {
  let loadError: string | null = null;
  const primary = await get13DGFeed({
    days: 90,
    limitN: 2000,
    includeOther: false,
    mappedOnly: true,
    universeOnly: true,
    includeLowQuality: false,
  }).catch((error) => {
    loadError = String(error);
    return null;
  });

  return (
    <div className="space-y-6">
      <section className="rounded-none p-6 shadow-panel">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-100">13D/G Activity</h1>
        <p className="mt-2 text-sm text-slate-400">
          Search and filter beneficial ownership events across mapped, in-universe institutions.
        </p>
      </section>

      <section>
        <FeedLiveTable rows={primary?.rows ?? []} loadError={loadError} />
      </section>
    </div>
  );
}
