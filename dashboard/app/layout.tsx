import type { Metadata } from "next";
import { IBM_Plex_Sans, JetBrains_Mono } from "next/font/google";

import "./globals.css";
import { NavLinks } from "@/components/nav-links";

// Self-hosted by Next.js (no external request at runtime, no layout shift from
// a late font swap) -- picked per prd.md section 20's Vercel/Linear/Raycast
// register: a plain technical sans for UI text, a mono for the data-dense
// numbers this dashboard is mostly made of.
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
  title: "AI Observatory",
  description: "The observability layer for AI coding agents. Runs entirely on your machine.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // `dark` is hard-set: dark-mode-first (PRD section 20), and there is no
    // theme switcher in this milestone's scope.
    <html lang="en" className={`dark ${fontSans.variable} ${fontMono.variable}`}>
      <body className="min-h-screen bg-background font-sans text-foreground">
        <div className="pointer-events-none fixed inset-0 bg-grid-fade" aria-hidden />
        <div className="relative mx-auto flex min-h-screen max-w-6xl flex-col px-6">
          <header className="sticky top-0 z-10 flex items-center justify-between border-b border-border/80 bg-background/80 py-5 backdrop-blur supports-[backdrop-filter]:bg-background/60">
            <a href="/" className="flex items-baseline gap-2">
              <span className="text-sm font-semibold tracking-tight">AI Observatory</span>
              <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <span className="h-1.5 w-1.5 rounded-full bg-success" aria-hidden />
                local
              </span>
            </a>
            <NavLinks />
          </header>

          <main className="flex-1 py-8">{children}</main>

          <footer className="border-t border-border py-5 text-xs text-muted-foreground">
            All data stays on this machine. No cloud, no accounts, no telemetry.
          </footer>
        </div>
      </body>
    </html>
  );
}
