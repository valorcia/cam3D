"use client";
import { useEffect } from "react";

export function SwRegister() {
  useEffect(() => {
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    // ask the browser not to evict the photos stored on the phone
    navigator.storage?.persist?.().catch(() => undefined);
  }, []);
  return null;
}
