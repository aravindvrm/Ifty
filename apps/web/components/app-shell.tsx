"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

import { AiChatWidget } from "@/components/ai-chat-widget";
import { AuthUserControl } from "@/components/auth-user-control";
import { InitialLoadOverlay } from "@/components/initial-load-overlay";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const selectedType = searchParams.get("type");
  const selectedKey = searchParams.get("key");
  const hasEntitySelection = Boolean(selectedType && selectedKey);
  const showInitialOverlay = pathname === "/explore" && !hasEntitySelection;
  const insiderActivityActive = pathname.startsWith("/activity/insiders");
  const boActivityActive = pathname.startsWith("/activity/13dg") || pathname === "/feed";
  const authPage = pathname.startsWith("/login") || pathname.startsWith("/signup");

  return (
    <div className="app-shell-root h-screen overflow-hidden text-slate-100">
      {showInitialOverlay ? <InitialLoadOverlay /> : null}

      <header className="fixed inset-x-0 top-0 z-30">
        <div className="mx-auto flex h-[4.25rem] w-full max-w-[1600px] items-center justify-between px-4 md:px-6 lg:px-8">
          <Link
            href="/explore"
            className="brand-link inline-flex shrink-0 items-center px-1 py-1.5"
            style={{ color: "#f8fafc", WebkitTextFillColor: "#f8fafc" }}
          >
            <span
              className="brand-wordmark brand-wordmark-sixtyfour text-2xl tracking-wide text-slate-100"
              style={{ color: "#f8fafc", WebkitTextFillColor: "#f8fafc" }}
            >
              Ifty
            </span>
          </Link>

          <div className="ml-auto flex items-center gap-4 md:gap-6">
            {!authPage ? (
              <nav className="flex items-center gap-4 text-sm font-medium text-slate-400 md:gap-6">
                <Link
                  href="/activity/insiders"
                  className={insiderActivityActive ? "text-white" : "transition hover:text-slate-100"}
                >
                  Insider Activity
                </Link>
                <Link
                  href="/activity/13dg"
                  className={boActivityActive ? "text-white" : "transition hover:text-slate-100"}
                >
                  13D/G Activity
                </Link>
              </nav>
            ) : null}
            <AuthUserControl />
          </div>
        </div>
      </header>

      <div className="app-main-scroll relative z-10 h-full overflow-y-auto pb-12">
        <main className="mx-auto w-full max-w-[1600px] px-4 pb-5 pt-[5.25rem] md:px-6 md:pb-6 md:pt-[5.5rem] lg:px-8">{children}</main>
      </div>

      {!authPage ? (
        <footer className="fixed inset-x-0 bottom-0 z-20 bg-black/20">
          <div className="mx-auto flex h-12 w-full max-w-[1600px] items-center justify-between px-4 text-xs text-slate-500 md:px-6 lg:px-8">
            <span>Ifty</span>
            <Link href="/institution" className="text-slate-300 transition hover:text-white">
              Institution Directory
            </Link>
          </div>
        </footer>
      ) : null}

      {!authPage ? <AiChatWidget /> : null}
    </div>
  );
}
