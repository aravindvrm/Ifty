import { ExploreWorkbench } from "@/components/explore-workbench";
import { MarketPulseView } from "@/components/market-pulse-view";
import type { ExploreSelection } from "@/components/explore-entity-view";

type ExploreType = "security" | "institution";

type Props = {
  searchParams: Promise<{
    type?: string;
    key?: string;
  }>;
};

function toExploreType(value: string | undefined): ExploreType | null {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (normalized === "security") return "security";
  if (normalized === "institution") return "institution";
  return null;
}

export default async function ExplorePage({ searchParams }: Props) {
  const params = await searchParams;
  const selectedType = toExploreType(params.type);
  const key = String(params.key ?? "").trim();

  const initialSelection: ExploreSelection | null = selectedType && key ? { type: selectedType, key } : null;

  return (
    <ExploreWorkbench
      defaultQuery={key}
      initialSelection={initialSelection}
      pulseContent={<MarketPulseView />}
    />
  );
}
