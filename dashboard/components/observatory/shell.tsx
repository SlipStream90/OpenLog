"use client";

import { ChevronLeft, Database, FileText, MoonStar, PlugZap, Search, SunDim } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

import { observatoryNavigation } from "./nav-config";

// ─────────────────────────────────────────────────────────────────────────────
// ObservatoryShell — Gridline-inspired sidebar + topbar but tailored to OpenLog
// Uses the Gridline layout primitives (fixed sidebar w-17, topbar h-18) and the
// teal primary (#0ab1ba) introduced via --primary, but keeps the zinc dark
// palette so existing pages don't flash. Skiper animated links are sprinkled in
// via the Link001-style hover (see components/ui/skiper-ui/skiper40.tsx) where
// appropriate — the shell itself stays restrained.
// ─────────────────────────────────────────────────────────────────────────────

function Logo() {
  return (
    <div className="flex items-center gap-2">
      <div className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground">
        <Database className="size-4" strokeWidth={2} />
      </div>
      <div className="hidden flex-col leading-none md:flex">
        <span className="text-xs font-semibold tracking-tight">OpenLog</span>
        <span className="text-[10px] font-mono text-muted-foreground">AI Observatory</span>
      </div>
    </div>
  );
}

function NavItem({ href, icon: Icon, label, active, showLabel, onNavigate }: any) {
  const className = cn(
    buttonVariants({ variant: "ghost", size: showLabel ? "lg" : "icon-lg" }),
    "rounded-lg text-muted-foreground",
    showLabel && "w-full justify-start gap-3",
    active && "bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary",
  );
  const content = (
    <>
      <Icon className={showLabel ? "size-5" : "size-[22px]"} strokeWidth={showLabel ? 1.7 : 1.6} />
      {showLabel && <span className="text-sm">{label}</span>}
    </>
  );
  if (showLabel) {
    return (
      <Link href={href} onClick={onNavigate} aria-current={active ? "page" : undefined} className={className}>
        {content}
      </Link>
    );
  }
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Link href={href} aria-label={label} aria-current={active ? "page" : undefined} className={className}>
          {content}
        </Link>
      </TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  );
}

function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="absolute inset-y-0 left-0 z-30 hidden w-[68px] flex-col items-center justify-between border-r border-sidebar-border bg-sidebar px-2.5 py-4 text-sidebar-foreground md:flex">
      <div className="flex w-full flex-col items-center gap-5">
        <div className="flex w-full justify-center border-b border-sidebar-border pb-4">
          <Link href="/" className="rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <Logo />
          </Link>
        </div>
        <nav className="flex flex-col items-center gap-2">
          {observatoryNavigation
            .filter((n) => !(n as any).isDetail)
            .map((item) => {
              const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href) && item.href === "/sessions" && pathname !== "/");
              // Sessions is active on both /sessions and /sessions/[id]
              const isActive = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return <NavItem key={item.href + item.label} href={item.href} icon={item.icon} label={item.label} active={isActive} />;
            })}
        </nav>
        <div className="h-px w-8 bg-sidebar-border" />
        <div className="flex flex-col items-center gap-1 text-[10px] font-mono text-muted-foreground">
          <span className="flex items-center gap-1">
            <span className="size-1.5 rounded-full bg-success animate-pulse" />
            local
          </span>
          <span className="hidden text-center leading-tight">100%<br />on-device</span>
        </div>
      </div>
      <div className="flex flex-col items-center gap-3">
        <Tooltip>
          <TooltipTrigger asChild>
            <a
              href="https://github.com/anomalyco/opencode"
              target="_blank"
              rel="noreferrer"
              className={cn(buttonVariants({ variant: "ghost", size: "icon-lg" }), "rounded-lg text-muted-foreground")}
              aria-label="OpenCode docs"
            >
              <FileText className="size-5" strokeWidth={1.6} />
            </a>
          </TooltipTrigger>
          <TooltipContent side="right">Docs</TooltipContent>
        </Tooltip>
        <div className="size-8 rounded-full bg-muted grid place-items-center font-mono text-xs font-medium">OL</div>
      </div>
    </aside>
  );
}

function Topbar({ isDark, onThemeChange }: { isDark: boolean; onThemeChange: (v: boolean) => void }) {
  const pathname = usePathname();
  const activeLabel =
    observatoryNavigation.find((n) => (n.href === "/" ? pathname === "/" : pathname.startsWith(n.href)))?.shortLabel ??
    "Today";
  const [query, setQuery] = useState("");
  return (
    <header className="absolute left-0 right-0 top-0 z-20 flex h-[72px] items-center justify-between gap-3 border-b border-sidebar-border bg-sidebar px-3 text-sidebar-foreground sm:px-5 md:left-[68px] md:px-6">
      <div className="flex min-w-0 items-center gap-3">
        <MobileNav isDark={isDark} onThemeChange={onThemeChange} />
        <span className="truncate text-sm font-semibold sm:hidden">{activeLabel}</span>
        {/* Status strip — gridline-style but observatory data */}
        <div className="hidden h-7 items-center overflow-hidden rounded-md bg-muted font-mono text-xs sm:flex">
          <span className="flex h-full items-center gap-1.5 border-r-2 border-sidebar px-2.5 text-primary">
            <span className="size-1.5 rounded-full bg-primary animate-pulse" />
            Observing
          </span>
          <span className="flex h-full items-center border-r-2 border-sidebar px-2.5 text-emerald-500">Local</span>
          <span className="flex h-full items-center px-2.5 text-muted-foreground">Offline OK</span>
        </div>
        <div className="hidden items-center gap-2 lg:flex">
          <form action="/search" method="get" className="relative" role="search">
            <label htmlFor="topbar-search" className="sr-only">
              Search sessions, files and commands
            </label>
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input
              id="topbar-search"
              name="q"
              defaultValue={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search sessions…"
              className="h-7 w-56 rounded-md border-0 bg-muted pl-7 pr-2 font-mono text-xs shadow-none placeholder:text-muted-foreground/60"
            />
          </form>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <div className="hidden items-center gap-2 text-xs md:flex">
          <span className="flex items-center gap-1.5 text-muted-foreground">
            <PlugZap className="size-3.5" />
            <span className="hidden xl:inline">Agents:</span>
          </span>
          <span className="inline-flex items-center gap-1 rounded-md bg-orange-500/10 px-1.5 py-0.5 font-mono text-[11px] text-orange-400">claude</span>
          <span className="inline-flex items-center gap-1 rounded-md bg-primary/10 px-1.5 py-0.5 font-mono text-[11px] text-primary">opencode</span>
          <span className="inline-flex items-center gap-1 rounded-md bg-violet-500/10 px-1.5 py-0.5 font-mono text-[11px] text-violet-400">kilo</span>
        </div>
        <div className="hidden items-center gap-2 md:flex">
          {isDark ? <MoonStar className="size-3.5" /> : <SunDim className="size-4" />}
          <Switch checked={isDark} onCheckedChange={onThemeChange} aria-label="Toggle theme" />
        </div>
        <div className="size-7 rounded-full bg-primary/15 grid place-items-center">
          <span className="text-xs font-medium text-primary">◐</span>
        </div>
      </div>
    </header>
  );
}

function MobileNav({ isDark, onThemeChange }: { isDark: boolean; onThemeChange: (v: boolean) => void }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger className={cn(buttonVariants({ variant: "ghost", size: "icon-lg" }), "md:hidden")}>
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
          <path d="M3 6h14M3 10h14M3 14h14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
        <span className="sr-only">Open navigation</span>
      </SheetTrigger>
      <SheetContent side="left" className="w-[280px] gap-0 border-sidebar-border bg-sidebar p-0 text-sidebar-foreground">
        <SheetHeader className="flex-row items-center justify-between gap-3 border-b border-sidebar-border px-4 py-3">
          <SheetTitle className="flex items-center gap-2 text-left">
            <Logo />
          </SheetTitle>
          <SheetClose className={cn(buttonVariants({ variant: "ghost", size: "icon" }))}>
            <ChevronLeft className="size-5" />
          </SheetClose>
          <SheetDescription className="sr-only">Navigation</SheetDescription>
        </SheetHeader>
        <nav className="flex flex-col gap-1 p-3">
          {observatoryNavigation
            .filter((n) => !(n as any).isDetail)
            .map((item) => {
              const isActive = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <NavItem
                  key={item.href}
                  href={item.href}
                  icon={item.icon}
                  label={item.label}
                  active={isActive}
                  showLabel
                  onNavigate={() => setOpen(false)}
                />
              );
            })}
        </nav>
        <div className="mt-auto border-t border-sidebar-border p-4">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-2 text-sm">
              {isDark ? <MoonStar className="size-4" /> : <SunDim className="size-4" />}
              {isDark ? "Dark" : "Light"}
            </span>
            <Switch checked={isDark} onCheckedChange={onThemeChange} aria-label="Toggle theme" />
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

export function ObservatoryShell({ children }: { children: React.ReactNode }) {
  const [isDark, setIsDark] = useState(() =>
    typeof document === "undefined" ? true : document.documentElement.classList.contains("dark"),
  );
  useEffect(() => {
    const root = document.documentElement;
    const sync = () => setIsDark(root.classList.contains("dark"));
    sync();
    const obs = new MutationObserver(sync);
    obs.observe(root, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);
  const handleThemeChange = (dark: boolean) => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("theme", dark ? "dark" : "light");
    setIsDark(dark);
  };
  return (
    <TooltipProvider>
      <div className="relative h-svh min-h-0 overflow-hidden bg-background text-foreground">
        <Sidebar />
        <Topbar isDark={isDark} onThemeChange={handleThemeChange} />
        <main className="h-full overflow-y-auto pt-[72px] md:pl-[68px]">
          <div className="mx-auto w-full max-w-6xl p-4 sm:p-6 lg:p-8">{children}</div>
          <footer className="mx-auto max-w-6xl border-t border-border px-6 py-4 text-center text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-2">
              <span className="size-1.5 rounded-full bg-success" />
              All data stays on this machine — no cloud, no telemetry — compatible with Claude, OpenCode & Kilo Code.
            </span>
          </footer>
        </main>
      </div>
    </TooltipProvider>
  );
}
