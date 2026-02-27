import type { Metadata } from "next";
import Link from "next/link";

import "./globals.css";

export const metadata: Metadata = {
  title: "Institutional Flow Tracker",
  description: "13F/13D-G institutional flow intelligence"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="shell-header">
          <div className="brand">Institutional Flow Tracker</div>
          <nav>
            <Link href="/">Home</Link>
            <Link href="/screeners">Screeners</Link>
            <Link href="/security">Security</Link>
            <Link href="/manager">Manager</Link>
            <Link href="/ops">Ops</Link>
          </nav>
        </header>
        <main className="shell-main">{children}</main>
      </body>
    </html>
  );
}
