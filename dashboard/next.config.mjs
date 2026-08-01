/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // No remote images, no analytics, no telemetry: this app must work with the
  // network disabled (PRD section 21). Disable Next's own telemetry too via
  // `npx next telemetry disable` -- see docs/setup.md.
};

export default nextConfig;
