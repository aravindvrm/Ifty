"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Sixtyfour_Convergence } from "next/font/google";
import { useMemo, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  Activity,
  Building2,
  ChevronLeft,
  Gauge,
  LayoutGrid,
  Menu,
  Settings,
} from "lucide-react";

import { EntitySearchInput } from "@/components/entity-search-input";
import { TopLiveTape } from "@/components/top-live-tape";
import { AiChatWidget } from "@/components/ai-chat-widget";

type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
};

const primaryNav: NavItem[] = [
  { href: "/", label: "Dashboard", icon: LayoutGrid },
  { href: "/feed", label: "13D/G Feed", icon: Activity },
  { href: "/security", label: "Securities", icon: Gauge },
  { href: "/institution", label: "Institutions", icon: Building2 },
  { href: "/ops", label: "Operations", icon: Settings },
];

const iftyWordmarkFont = Sixtyfour_Convergence({
  subsets: ["latin"],
  weight: "400",
  display: "swap",
});

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(true);

  const sidebarWidth = collapsed ? "w-[86px]" : "w-[260px]";
  const sidebarHeaderClass = collapsed ? "justify-center px-0" : "justify-end px-4";
  const nav = useMemo(() => primaryNav, []);

  return (
    <div className="h-screen overflow-hidden text-slate-100">
      <div className="flex h-full">
        <aside
          className={[
            "hidden h-full md:flex flex-col bg-black/85 backdrop-blur-[1px] transition-[width] duration-300 ease-out",
            sidebarWidth,
          ].join(" ")}
        >
          <div className={`flex h-16 items-center ${sidebarHeaderClass}`}>
            <button
              type="button"
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              onClick={() => setCollapsed((value) => !value)}
              className="sidebar-circle inline-flex h-9 w-9 items-center justify-center border border-line/70 bg-card/70 text-slate-300 transition hover:border-accentBlue/60 hover:bg-card/85 hover:text-slate-100"
            >
              {collapsed ? <Menu className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
            </button>
          </div>

          <div className="flex min-h-0 flex-1 flex-col border-r border-line/80">
            <nav className="app-sidebar-scroll flex-1 space-y-1 overflow-y-auto px-3 py-4">
              {nav.map((item) => {
                const Icon = item.icon;
                const active = pathname === item.href || (item.href !== "/" && pathname?.startsWith(item.href));
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    title={collapsed ? item.label : undefined}
                    className={[
                      collapsed
                        ? "group sidebar-circle mx-auto flex h-11 w-11 items-center justify-center border text-sm transition-all"
                        : "group flex items-center rounded-none border px-3 py-2.5 text-sm transition-all gap-3",
                      collapsed
                        ? active
                          ? "border-accentBlue/60 bg-accentBlue/18 text-white shadow-[0_0_0_1px_rgba(43,196,255,.24)_inset,0_0_14px_rgba(43,196,255,.18)]"
                          : "border-line/45 text-slate-400 hover:border-line/85 hover:bg-card/80 hover:text-slate-200"
                        : active
                          ? "border-accentBlue/55 bg-accentBlue/15 text-white shadow-[0_0_0_1px_rgba(43,196,255,.16)_inset]"
                          : "border-transparent text-slate-400 hover:border-line/80 hover:bg-card/80 hover:text-slate-200",
                    ].join(" ")}
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    {!collapsed ? <span>{item.label}</span> : null}
                  </Link>
                );
              })}
            </nav>

            <div className="border-t border-line/80 px-4 py-3 text-[11px] text-slate-500">
              {!collapsed ? "v1 Interface Rework" : "v1"}
            </div>
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <div className="app-main-scroll min-h-0 flex-1 overflow-y-auto">
            <header className="sticky top-0 z-20 border-b border-line/90 bg-black/45 shadow-[inset_0_-1px_0_rgba(39,65,87,0.55)] backdrop-blur-md backdrop-saturate-150 supports-[backdrop-filter]:bg-black/30">
              <div className="flex h-16 items-center px-4 md:px-6">
                <div className="flex w-full items-center gap-3">
                  <TopLiveTape className="hidden min-w-0 flex-1 md:block" />
                  <div className="ml-auto flex min-w-0 items-center gap-3">
                    <EntitySearchInput
                      placeholder="Search securities, institutions, filings..."
                      fallbackPath="/security"
                      showIcon
                      className="relative w-[17rem] sm:w-[19rem] md:w-[22rem] lg:w-[24rem]"
                      inputClassName="w-full rounded-none border border-line/80 bg-card/70 py-1.5 pl-9 pr-3 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-accentBlue/70"
                      dropdownClassName="absolute left-0 right-0 top-[calc(100%+8px)] z-30 overflow-hidden rounded-none border border-line/80 bg-[#02050c] shadow-panel"
                    />
                    <div className="inline-flex items-center px-1 py-1.5">
                      <span className={`${iftyWordmarkFont.className} text-2xl tracking-wide text-slate-100`}>Ifty</span>
                    </div>
                  </div>
                </div>
              </div>
            </header>

            <main className="mx-auto w-full max-w-[1600px] px-4 py-5 md:px-6 md:py-6 lg:px-8">{children}</main>
          </div>
        </div>
      </div>
      <AiChatWidget />
    </div>
  );
}
