import type { NextConfig } from "next";

// Static export: the UI is served by the local FastAPI server (same origin as
// the API), so the phone's pairing cookie and future HTTPS work without CORS.
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
};

export default nextConfig;
