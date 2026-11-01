import type { Metadata, Viewport } from "next";
import { SwRegister } from "@/components/SwRegister";
import "./globals.css";

export const metadata: Metadata = {
  title: "cam3D Capture",
  description: "Capture photo pour scans 3D, chiffrée de bout en bout",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icon.svg", apple: "/icon.svg" },
  appleWebApp: { capable: true, title: "cam3D", statusBarStyle: "black-translucent" },
};

export const viewport: Viewport = { themeColor: "#0a0b0e", width: "device-width", initialScale: 1, viewportFit: "cover" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <body>
        <SwRegister />
        <main className="mx-auto min-h-dvh max-w-xl px-4 pb-10" style={{ paddingTop: "max(16px, env(safe-area-inset-top))" }}>{children}</main>
      </body>
    </html>
  );
}
