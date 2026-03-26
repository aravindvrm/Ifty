import { redirect } from "next/navigation";

type Props = { params: Promise<{ managerKey: string }> };

export default async function LegacyManagerRedirect({ params }: Props) {
  const { managerKey } = await params;
  redirect(`/explore?type=institution&key=${encodeURIComponent(managerKey)}`);
}
