import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Pin Turbopack's workspace root to this directory. Without it, Next infers
  // the root from stray lockfiles higher up (e.g. C:\Users\<name>\package-lock.json)
  // and page resolution breaks under `next build` (Next 16 uses Turbopack).
  turbopack: {
    root: __dirname,
  },
  // No remote images, no analytics, no telemetry: this app must work with the
  // network disabled (PRD section 21). Disable Next's own telemetry too via
  // `npx next telemetry disable` -- see docs/setup.md.
};

export default nextConfig;
