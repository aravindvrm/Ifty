"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Sixtyfour_Convergence } from "next/font/google";
import { useMemo } from "react";

import { TopLiveTape } from "@/components/top-live-tape";
import { AiChatWidget } from "@/components/ai-chat-widget";

type NavItem = {
  href: string;
  label: string;
};

const topNav: NavItem[] = [
  { href: "/feed", label: "13D/G" },
  { href: "/institution", label: "Institutions" },
];

const iftyWordmarkFont = Sixtyfour_Convergence({
  subsets: ["latin"],
  weight: "400",
  display: "swap",
});

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const nav = useMemo(() => topNav, []);

  return (
    <div className="h-screen overflow-hidden text-slate-100">
      <div className="app-main-scroll h-full overflow-y-auto">
        <header className="sticky top-0 z-20 bg-black/45 backdrop-blur-md backdrop-saturate-150 supports-[backdrop-filter]:bg-black/30">
          <div className="flex h-16 items-center gap-4 px-4 md:px-6">
            <Link href="/explore" className="inline-flex shrink-0 items-center px-1 py-1.5">
              <span className={`${iftyWordmarkFont.className} text-2xl tracking-wide text-slate-100`}>Ifty</span>
            </Link>

            <TopLiveTape className="hidden min-w-0 flex-1 md:block" />

            <nav className="ml-auto flex items-center gap-4">
              {nav.map((item) => {
                const active = pathname === item.href || pathname?.startsWith(`${item.href}/`);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={[
                      "px-1 py-1.5 text-sm transition-colors",
                      active
                        ? "text-accentBlue"
                        : "text-slate-300 hover:text-slate-100",
                    ].join(" ")}
                  >
                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1600px] px-4 py-5 md:px-6 md:py-6 lg:px-8">{children}</main>
      </div>

      <AiChatWidget />
    </div>
  );
}
