# cam3D — interface Web

Next.js 16 (export statique) · React 19 · TypeScript · Tailwind CSS 4 ·
Three.js / React Three Fiber · Zustand.

L'interface est compilée en fichiers statiques (`out/`) servis par l'API locale
FastAPI : une seule origine, donc le cookie d'appairage du téléphone et le futur
HTTPS fonctionnent sans CORS. Aucune ressource n'est chargée depuis Internet
(pas de police distante, pas de CDN, décodeur Draco désactivé).

```bash
npm ci
npm run build        # -> out/, servi automatiquement par `cam3d serve`
npm run dev          # développement sur :3000, API attendue sur :8765 (voir .env.development)
npm run lint         # vérification TypeScript
npm test             # tests unitaires (vitest)
CAM3D_URL=http://127.0.0.1:8765 CAM3D_PHOTOS=/chemin/photos node tests/e2e.mjs   # parcours complet Playwright
```

| Dossier | Contenu |
|---|---|
| `src/app/` | pages : accueil, projets, projet (`?id=&tab=`), paramètres, appairage |
| `src/components/` | visualiseur 3D, panneaux photos / reconstruction / exports, journaux |
| `src/lib/` | client API, store Zustand + WebSocket, formatage (testé) |
| `tests/e2e.mjs` | scénario Playwright : import, reconstruction réelle, visualiseur, export DAE, appairage téléphone |
