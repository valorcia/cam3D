import type { NextConfig } from "next";

// cam3D Capture: mobile capture app hosted on Vercel (HTTPS, works anywhere).
// Pages are static (offline-capable through public/sw.js); /api/* are the
// encrypted-relay routes (Vercel Functions).
const nextConfig: NextConfig = {
  trailingSlash: true,
  skipTrailingSlashRedirect: true, // /api/* must answer directly (the PC refuses redirects)
  reactStrictMode: true,
  async headers() {
    return [
      { source: "/sw.js", headers: [{ key: "Cache-Control", value: "no-cache" }, { key: "Service-Worker-Allowed", value: "/" }] },
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "Permissions-Policy", value: "camera=(self), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
