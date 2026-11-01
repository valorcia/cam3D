# cam3D — scan 3D photoréaliste, gratuit et local

cam3D transforme des photographies (smartphone ou appareil photo) en modèles 3D
texturés, **entièrement sur votre ordinateur**, sans abonnement, sans crédits,
sans cloud. Les modèles s'exportent en **DAE (SketchUp)**, OBJ, GLB, STL et PLY.

```
Téléphone, n'importe où (cam3D Capture, en ligne) ──photos chiffrées / ZIP──┐
Téléphone, même Wi-Fi (interface locale)  ──photos──────────────────────────┤
                                                                             ▼
Ordinateur (API locale) ──▶ COLMAP (caméras) ──▶ OpenMVS (dense, maillage, textures)
                        ──▶ nettoyage ──▶ visualiseur 3D ──▶ exports DAE / OBJ / GLB / STL / PLY
```

Deux façons de capturer :

- **n'importe où**, sans ordinateur allumé : l'application **cam3D Capture**
  (`capture/`, hébergée sur Vercel) garde les photos sur le téléphone, même hors
  connexion, et les envoie **chiffrées de bout en bout** vers un relais
  temporaire ; vous les récupérez ensuite dans cam3D avec un code de transfert
  (ou par partage / ZIP, sans relais) ;
- **à côté de l'ordinateur** : l'interface locale, appairée par QR code.

## État du projet

| Phase | Contenu | État |
|---|---|---|
| 1 | Audit technique, choix d'architecture | ✅ terminé (voir `ARCHITECTURE.md`) |
| 2 | **Moteur de reconstruction réel** : photos → OBJ texturé → DAE | ✅ fonctionnel, testé sur un jeu de photos réel |
| 3 | API locale FastAPI, projets, tâches, appairage | ✅ fonctionnel, testé (voir `API.md`) |
| 4 | Interface Web (Next.js, visualiseur Three.js) | ✅ fonctionnelle, testée de bout en bout (Playwright) |
| 5 | Capture mobile (QR code, HTTPS local, caméra, vidéo) | ✅ testée en émulation ; à valider sur iPhone/Android réels |
| 6 | Nettoyage non destructif, simplification re-texturée, étalonnage, mesures, Export SketchUp | ✅ fonctionnel, testé |
| 7 | Validation complète | ✅ sous Linux sur clone neuf (tous tests verts) ; ⏳ SketchUp, iPhone/Android réels, Windows, macOS |

Ce qui a été **réellement testé** à ce jour est décrit dans `TESTING.md`.

### Critères de réussite de la V1

| # | Critère | État |
|---|---|---|
| 1 | Créer un projet | ✅ testé (interface + API) |
| 2 | Importer de véritables photographies | ✅ galerie, glisser-déposer, capture navigateur, appareil natif, vidéo, capture à distance (relais chiffré), ZIP |
| 3 | Reconstruire un modèle 3D | ✅ jeu réel Sceaux : 11/11 caméras ; photos prises dans le navigateur : 15/15 |
| 4 | Géométrie et textures | ✅ maillage texturé (atlas photographique) |
| 5 | Visible dans le navigateur | ✅ visualiseur Three.js, 4 modes, vues ortho |
| 6 | Enregistrer le projet | ✅ bibliothèque locale, reprise, duplication, archivage |
| 7 | Export OBJ | ✅ |
| 8 | Export DAE avec textures | ✅ ZIP DAE + textures, profil Export SketchUp vérifié automatiquement |
| 9 | DAE ouvert dans un logiciel compatible | ✅ Blender 4.5 et Assimp ; ⏳ **SketchUp à valider sur un poste réel** |
| 10 | Erreurs gérées | ✅ messages explicites, conseils, plantages isolés, annulation, reprise |
| 11 | Aucun service payant | ✅ uniquement des logiciels libres locaux |
| 12 | Fonctionnement local | ✅ reconstruction et stockage des projets sur l'ordinateur ; le relais de capture à distance est optionnel et ne voit que des données chiffrées |
La compatibilité SketchUp n'est pas encore validée sur une installation réelle de
SketchUp ; l'import a été validé dans Blender 4.5 (importateur COLLADA officiel) et
avec Assimp.

## Démarrage rapide (développeur, Linux / macOS)

```bash
./scripts/install.sh                      # venv Python + dépendances + diagnostic
sudo ./scripts/build_openmvs_linux.sh     # Linux : compile OpenMVS (macOS : brew install openmvs)
source .venv/bin/activate
cam3d doctor                              # matériel + outils détectés
cam3d reconstruct /chemin/photos /chemin/projet --profile fast --export obj,dae,glb
(cd frontend && npm ci && npm run build)  # interface Web
cam3d serve --host 0.0.0.0              # interface : http://127.0.0.1:8765  ·  API : /docs
```

Le projet produit `meshes/model.obj`, `textures/`, `previews/model.glb` et les
archives `exports/model_dae.zip` (DAE + textures, prêt pour SketchUp) et
`exports/model_obj.zip`.

## Documentation

- `ARCHITECTURE.md` — architecture, choix techniques, licences
- `INSTALLATION.md` — installation par système, dépendances
- `DEVELOPMENT.md` — organisation du code, conventions, comment contribuer
- `PHOTOGRAMMETRY.md` — pipeline de reconstruction, profils, paramètres réels
- `EXPORT_FORMATS.md` — formats d'export, profil « Export SketchUp »
- `TESTING.md` — stratégie de tests et résultats mesurés
- `API.md` — API locale, appairage et sécurité
- `capture/README.md` — application de capture à distance, relais chiffré, déploiement Vercel
- `ROADMAP.md` — phases suivantes et évolutions

## Licence et composants

cam3D (ce dépôt) est publié sous licence MIT. Il s'appuie sur des logiciels
open source exécutés localement : COLMAP (BSD-3), OpenMVS (AGPL-3, exécuté comme
processus séparé), Open3D (MIT), trimesh (MIT), pycollada (BSD), OpenCV
(Apache-2), FFmpeg (LGPL/GPL). Détails dans `ARCHITECTURE.md`.
