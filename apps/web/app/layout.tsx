import type { Metadata } from "next";
import { AppShell } from "@/components/app-shell";

import "./globals.css";

export const metadata: Metadata = {
  title: "Ifty",
  description: "13F/13D-G institutional flow intelligence"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen antialiased bg-texture-grain">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
