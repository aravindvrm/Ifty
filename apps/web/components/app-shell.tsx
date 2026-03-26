"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Sixtyfour_Convergence } from "next/font/google";

import { AiChatWidget } from "@/components/ai-chat-widget";
import { InitialLoadOverlay } from "@/components/initial-load-overlay";

const iftyWordmarkFont = Sixtyfour_Convergence({
  subsets: ["latin"],
  weight: "400",
  display: "swap",
});

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const selectedType = searchParams.get("type");
  const selectedKey = searchParams.get("key");
  const hasEntitySelection = Boolean(selectedType && selectedKey);
  const showInitialOverlay = pathname === "/explore" && !hasEntitySelection;

  return (
    <div className="h-screen overflow-hidden text-slate-100">
      {showInitialOverlay ? <InitialLoadOverlay /> : null}

      <Link
        href="/explore"
        className="brand-link fixed left-4 top-4 z-30 inline-flex shrink-0 items-center px-1 py-1.5 md:left-6 md:top-5"
        style={{ color: "#f8fafc", WebkitTextFillColor: "#f8fafc" }}
      >
        <span
          className={`${iftyWordmarkFont.className} brand-wordmark text-2xl tracking-wide text-slate-100`}
          style={{ color: "#f8fafc", WebkitTextFillColor: "#f8fafc" }}
        >
          Ifty
        </span>
      </Link>

      <div className="app-main-scroll h-full overflow-y-auto">
        <main className="mx-auto w-full max-w-[1600px] px-4 pb-5 pt-20 md:px-6 md:pb-6 md:pt-24 lg:px-8">{children}</main>

        <footer className="border-t border-line/70 bg-black/20">
          <div className="mx-auto flex h-12 w-full max-w-[1600px] items-center justify-between px-4 text-xs text-slate-500 md:px-6 lg:px-8">
            <span>Ifty</span>
            <Link href="/institution" className="text-slate-300 transition hover:text-white">
              Institution Directory
            </Link>
          </div>
        </footer>
      </div>

      <AiChatWidget />
    </div>
  );
}
