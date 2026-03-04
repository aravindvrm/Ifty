import Link from "next/link";

import { FeedLiveTable } from "@/components/feed-live-table";
import { get13DGFeed } from "@/lib/api";

export default async function FeedPage() {
  let loadError: string | null = null;
  const primary = await get13DGFeed({
    days: 90,
    limitN: 2000,
    includeOther: false,
    mappedOnly: true,
    includeLowQuality: false
  }).catch((error) => {
    loadError = String(error);
    return null;
  });

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-line/80 bg-card/80 p-6 shadow-panel">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-100">13D/G Event Feed</h1>
        <p className="mt-2 text-sm text-slate-400">
          Daily-updated beneficial ownership event stream across the active institution universe.
        </p>
      </section>

      <section className="rounded-2xl border border-line/80 bg-card/80 p-5 shadow-panel">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-slate-100">Live Feed Explorer</h2>
          <Link href="/" className="text-sm text-accentBlue hover:text-white">
            Back to dashboard
          </Link>
        </div>
        <FeedLiveTable rows={primary?.rows ?? []} loadError={loadError} />
      </section>
    </div>
  );
}
