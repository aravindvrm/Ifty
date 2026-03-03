import { redirect } from "next/navigation";

export default function LegacyManagerDirectoryRedirect() {
  redirect("/institution");
}
