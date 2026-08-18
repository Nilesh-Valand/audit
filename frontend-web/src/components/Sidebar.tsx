"use client";

import type { LucideIcon } from "lucide-react";
import {
  FileSearch,
  FileText,
  FolderKanban,
  LayoutDashboard,
  ListChecks,
  PlusCircle,
  ScanSearch,
  Settings,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

type NavItem = {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
};

type NavSection = {
  title: string;
  items: NavItem[];
};

const navSections: NavSection[] = [
  {
    title: "Workspace",
    items: [
      { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
      { to: "/audits/new", label: "New Audit", icon: PlusCircle },
      { to: "/projects", label: "Projects", icon: FolderKanban },
    ],
  },
  {
    title: "Analysis",
    items: [
      { to: "/issues", label: "Issues", icon: ListChecks },
      { to: "/pages", label: "Pages", icon: FileSearch },
      { to: "/report", label: "Report", icon: FileText },
    ],
  },
  {
    title: "Tools",
    items: [
      { to: "/current-page", label: "Current Page Check", icon: ScanSearch },
      { to: "/settings", label: "Settings", icon: Settings },
    ],
  },
];

function isNavActive(pathname: string, to: string, end?: boolean): boolean {
  if (end) return pathname === to;
  return pathname === to || pathname.startsWith(`${to}/`);
}

export function Sidebar() {
  const pathname = usePathname() ?? "";

  return (
    <aside className="sticky top-0 z-20 flex h-screen w-72 shrink-0 flex-col self-start border-r border-slate-200 bg-white text-slate-700">
      <div className="flex items-center gap-3 px-5 py-5">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-sky-500 to-brand-700 shadow-sm shadow-sky-200/60">
          <ScanSearch className="h-5 w-5 text-white" strokeWidth={2.25} />
        </div>
        <div className="min-w-0">
          <div className="truncate text-[15px] font-semibold tracking-tight text-slate-900">
            SEO Audit
          </div>
          <div className="truncate text-xs font-medium text-slate-400">
            Site crawler & scoring
          </div>
        </div>
      </div>

      <nav className="flex-1 space-y-6 overflow-y-auto px-3.5 pb-5">
        {navSections.map((section) => (
          <div key={section.title}>
            <div className="mb-2 px-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
              {section.title}
            </div>
            <div className="space-y-1.5">
              {section.items.map((item) => {
                const Icon = item.icon;
                const isActive = isNavActive(pathname, item.to, item.end);
                return (
                  <Link
                    key={item.to}
                    href={item.to}
                    className={[
                      "group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors",
                      isActive
                        ? "bg-sky-50 text-sky-800"
                        : "text-slate-600 hover:bg-slate-50 hover:text-slate-900",
                    ].join(" ")}
                  >
                    {isActive ? (
                      <span className="absolute inset-y-2 left-0 w-[3px] rounded-full bg-sky-500" />
                    ) : null}
                    <Icon
                      className={[
                        "h-5 w-5 shrink-0",
                        isActive
                          ? "text-sky-600"
                          : "text-slate-400 group-hover:text-slate-600",
                      ].join(" ")}
                      strokeWidth={2}
                    />
                    <span className="truncate">{item.label}</span>
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      <div className="border-t border-slate-200 px-5 py-4">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate text-xs font-medium text-slate-600">Local workspace</div>
            <div className="truncate text-[11px] text-slate-400">Backend · 127.0.0.1:8000</div>
          </div>
          <span className="shrink-0 rounded-md bg-slate-50 px-2 py-1 text-[11px] font-semibold tabular-nums text-slate-400 ring-1 ring-inset ring-slate-200">
            v0.1.0
          </span>
        </div>
      </div>
    </aside>
  );
}
