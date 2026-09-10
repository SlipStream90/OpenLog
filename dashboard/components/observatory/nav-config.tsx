"use client";

import { Clock3, House, ListTree, Search, Sparkles, Terminal } from "lucide-react";

export const observatoryNavigation = [
  { href: "/", label: "Today", shortLabel: "Today", icon: House },
  { href: "/sessions", label: "Sessions", shortLabel: "Sessions", icon: Clock3 },
  { href: "/sessions", label: "Timeline Replay", shortLabel: "Timeline", icon: ListTree, isDetail: true },
] as const;

export const agentMeta: Record<string, { label: string; color: string; dot: string }> = {
  claude: { label: "Claude Code", color: "text-orange-400", dot: "bg-orange-500" },
  opencode: { label: "OpenCode", color: "text-primary", dot: "bg-primary" },
  kilocode: { label: "Kilo Code", color: "text-violet-400", dot: "bg-violet-500" },
  codex: { label: "Codex", color: "text-sky-400", dot: "bg-sky-500" },
};
