// Minimal inline icon set (no icon font, no network request).
type P = { className?: string };
const base = "h-5 w-5";
const S = ({ className, children }: P & { children: React.ReactNode }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" className={className ?? base} aria-hidden>
    {children}
  </svg>
);
export const IconPlus = (p: P) => <S {...p}><path d="M12 5v14M5 12h14" /></S>;
export const IconCube = (p: P) => <S {...p}><path d="M12 3 4 7.5v9L12 21l8-4.5v-9L12 3Z" /><path d="m4 7.5 8 4.5 8-4.5M12 12v9" /></S>;
export const IconImages = (p: P) => <S {...p}><rect x="3" y="5" width="14" height="12" rx="2" /><path d="M7 21h12a2 2 0 0 0 2-2V9" /><path d="m3 14 4-4 4 4 2-2 4 4" /></S>;
export const IconFolder = (p: P) => <S {...p}><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" /></S>;
export const IconGear = (p: P) => <S {...p}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" /></S>;
export const IconTrash = (p: P) => <S {...p}><path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3" /></S>;
export const IconDownload = (p: P) => <S {...p}><path d="M12 4v11m0 0-4-4m4 4 4-4M5 20h14" /></S>;
export const IconUpload = (p: P) => <S {...p}><path d="M12 20V9m0 0-4 4m4-4 4 4M5 4h14" /></S>;
export const IconCheck = (p: P) => <S {...p}><path d="m5 12 4.5 4.5L19 7" /></S>;
export const IconX = (p: P) => <S {...p}><path d="M6 6l12 12M18 6 6 18" /></S>;
export const IconAlert = (p: P) => <S {...p}><path d="M12 9v4m0 4h.01M10.3 3.9 2.4 17.5A2 2 0 0 0 4.1 20.5h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" /></S>;
export const IconPhone = (p: P) => <S {...p}><rect x="7" y="2.5" width="10" height="19" rx="2.5" /><path d="M11 18.5h2" /></S>;
export const IconBack = (p: P) => <S {...p}><path d="M15 18l-6-6 6-6" /></S>;
export const IconDots = (p: P) => <S {...p}><circle cx="5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /></S>;
export const IconPlay = (p: P) => <S {...p}><path d="M7 5v14l11-7L7 5Z" /></S>;
export const IconRefresh = (p: P) => <S {...p}><path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7" /></S>;
export const IconTarget = (p: P) => <S {...p}><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3" /></S>;
