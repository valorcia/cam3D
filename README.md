# cam3D — scan 3D photoréaliste, gratuit et local

cam3D transforme des photographies (smartphone ou appareil photo) en modèles 3D
texturés, **entièrement sur votre ordinateur**, sans abonnement, sans crédits,
sans cloud. Les modèles s'exportent en **DAE (SketchUp)**, OBJ, GLB, STL et PLY.

```
Téléphone ──photos──▶ Ordinateur (API locale) ──▶ COLMAP (caméras) ──▶ OpenMVS (dense, maillage, textures)
                                                ──▶ nettoyage ──▶ visualiseur 3D ──▶ exports DAE / OBJ / GLB / STL / PLY
```

## État du projet

| Phase | Contenu | État |
|---|---|---|
| 1 | Audit technique, choix d'architecture | ✅ terminé (voir `ARCHITECTURE.md`) |
| 2 | **Moteur de reconstruction réel** : photos → OBJ texturé → DAE | ✅ fonctionnel, testé sur un jeu de photos réel |
| 3 | API locale FastAPI, gestion de projets et de tâches | ⏳ à venir |
| 4 | Interface Web (Next.js, visualiseur Three.js) | ⏳ |
| 5 | Capture mobile (PWA, QR code, HTTPS local) | ⏳ |
| 6 | Profils qualité avancés, nettoyage interactif, étalonnage, mesures | ⏳ (profils déjà en place) |
| 7 | Validation complète téléphone → SketchUp | ⏳ |

Ce qui a été **réellement testé** à ce jour est décrit dans `TESTING.md`.
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
- `ROADMAP.md` — phases suivantes et évolutions

## Licence et composants

cam3D (ce dépôt) est publié sous licence MIT. Il s'appuie sur des logiciels
open source exécutés localement : COLMAP (BSD-3), OpenMVS (AGPL-3, exécuté comme
processus séparé), Open3D (MIT), trimesh (MIT), pycollada (BSD), OpenCV
(Apache-2), FFmpeg (LGPL/GPL). Détails dans `ARCHITECTURE.md`.
