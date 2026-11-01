import type { Metadata, Viewport } from "next";
import { Shell } from "@/components/Shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "cam3D",
  description: "Scan 3D photoréaliste, gratuit et local",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icon.svg" },
  appleWebApp: { capable: true, title: "cam3D", statusBarStyle: "black-translucent" },
};

export const viewport: Viewport = { themeColor: "#0a0b0e", width: "device-width", initialScale: 1, viewportFit: "cover" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <body><Shell>{children}</Shell></body>
    </html>
  );
}
