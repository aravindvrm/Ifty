import { redirect } from "next/navigation";

type Props = {
  params: Promise<{ ticker: string }>;
};

export default async function SecurityPage({ params }: Props) {
  const { ticker } = await params;
  redirect(`/explore?type=security&key=${encodeURIComponent(ticker)}`);
}
