import type { Metadata } from "next";
import { IBM_Plex_Sans, JetBrains_Mono } from "next/font/google";

import "./globals.css";
import { ObservatoryShell } from "@/components/observatory/shell";

const fontSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-sans",
  display: "swap",
});

const fontMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "OpenLog — AI Observatory",
  description: "The observability layer for AI coding agents. Local-first, compatible with Claude Code, OpenCode & Kilo Code.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`dark ${fontSans.variable} ${fontMono.variable}`} suppressHydrationWarning>
      <body className="min-h-screen bg-background font-sans text-foreground antialiased">
        <div className="pointer-events-none fixed inset-0 bg-grid-fade" aria-hidden />
        <ObservatoryShell>{children}</ObservatoryShell>
      </body>
    </html>
  );
}
