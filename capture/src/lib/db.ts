/** Phone-side storage (IndexedDB): scans and their photos stay on the phone. */
export interface Scan {
  id: string;            // 32 hex chars, also the relay folder name
  name: string;
  created: number;
  key: string;           // base64url AES key (never leaves the phone except inside the transfer code)
  relay: boolean;        // send encrypted copies to the relay when online
  manifestUrl?: string;  // set once a manifest has been uploaded
  manifestCount?: number;
}

export interface Photo {
  id: string;            // 32 hex chars
  scanId: string;
  name: string;
  type: string;
  size: number;
  created: number;
  blob: Blob;
  sharpness?: number;
  brightness?: number;
  warnings?: string[];
  uploaded: boolean;     // encrypted copy present on the relay
  sha256?: string;
  heading?: number | null; // compass heading when taken (continuous scan), for the coverage ring
  tilt?: number | null;    // height band 0 high / 1 middle / 2 low
  auto?: boolean;          // picked automatically by the continuous scan
}

const DB = "cam3d-capture";
let dbp: Promise<IDBDatabase> | null = null;

function open(): Promise<IDBDatabase> {
  if (dbp) return dbp;
  dbp = new Promise((resolve, reject) => {
    const r = indexedDB.open(DB, 1);
    r.onupgradeneeded = () => {
      const db = r.result;
      db.createObjectStore("scans", { keyPath: "id" });
      const p = db.createObjectStore("photos", { keyPath: "id" });
      p.createIndex("scanId", "scanId");
    };
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
  return dbp;
}

function req<T>(r: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => { r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });
}

async function store(name: "scans" | "photos", mode: IDBTransactionMode = "readonly") {
  return (await open()).transaction(name, mode).objectStore(name);
}

export const db = {
  scans: async (): Promise<Scan[]> => (await req((await store("scans")).getAll() as IDBRequest<Scan[]>)).sort((a, b) => b.created - a.created),
  scan: async (id: string): Promise<Scan | undefined> => req((await store("scans")).get(id) as IDBRequest<Scan | undefined>),
  putScan: async (s: Scan) => { await req((await store("scans", "readwrite")).put(s)); },
  deleteScan: async (id: string) => {
    for (const p of await db.photos(id)) await db.deletePhoto(p.id);
    await req((await store("scans", "readwrite")).delete(id));
  },
  photos: async (scanId: string): Promise<Photo[]> =>
    (await req((await store("photos")).index("scanId").getAll(scanId) as IDBRequest<Photo[]>)).sort((a, b) => a.created - b.created),
  putPhoto: async (p: Photo) => { await req((await store("photos", "readwrite")).put(p)); },
  deletePhoto: async (id: string) => { await req((await store("photos", "readwrite")).delete(id)); },
};

export const settings = {
  get relayKey(): string { try { return localStorage.getItem("cam3d.relayKey") ?? ""; } catch { return ""; } },
  set relayKey(v: string) { try { localStorage.setItem("cam3d.relayKey", v); } catch { /* private mode */ } },
};
