# Architecture

## Vue d'ensemble

```
smartphone (PWA) ──HTTP(S) local──▶ backend/cam3d/server  (FastAPI)
                               ├─ app.py        routes /api (voir API.md), WebSocket /api/events
                               ├─ projects.py   bibliothèque, validation des photos, metadata.json
                               ├─ jobs.py       file d'attente, worker isolé, annulation, reprise, estimations
                               ├─ security.py   appairage (code + approbation), jetons hachés
                               ├─ db.py         SQLite (projects, photos, jobs, devices)
                               └─ ../worker.py  processus de reconstruction (protocole JSON « CAM3D … »)
                                        │
                                        ▼
                               backend/cam3d/engine  (Python, indépendant du Web)
                               ├─ hardware.py   détection OS/CPU/RAM/GPU/disque
                               ├─ tools.py      découverte COLMAP / OpenMVS / Blender / FFmpeg
                               ├─ profiles.py   RAPIDE / HAUTE QUALITÉ / ULTRA → vrais paramètres
                               ├─ events.py     événements de progression, journaux, annulation
                               ├─ mesh_io.py    modèle texturé (parts + UV + textures), OBJ in/out
                               ├─ pipeline.py   orchestrateur (reprise, résultats, dossiers projet)
                               └─ stages/
                                   prepare.py    validation, flou, luminosité, redimensionnement
                                   sfm.py        COLMAP via pycolmap (features, matching, mapping)
                                   mvs.py        OpenMVS : undistort → Densify → ReconstructMesh → (RefineMesh) → TextureMesh
                                   meshfilter.py suppression des surfaces hallucinées (ciel, fond)
                                   cleanup.py    composants isolés, faces dégénérées, repère canonique
                                   dae.py        écriture COLLADA pour SketchUp (pycollada)
                                   export.py     OBJ / GLB / STL / PLY / DAE (+ zip)
                                        │
                                        ▼
                               frontend/ (Next.js export statique, servi par FastAPI sur la même origine)
                               ├─ src/app/          accueil, projets, projet ?id=&tab=, paramètres, appairage
                               ├─ src/components/   Viewer3D (R3F), panneaux photos / reconstruction / exports
                               └─ src/lib/          client API, store Zustand + WebSocket /api/events
```

Interface :

- **Même origine** : `cam3d serve` sert `frontend/out/` et `/api`. Le cookie
  HttpOnly du téléphone fonctionne pour images, modèles et WebSocket, sans CORS.
- **Aucune ressource externe** : pas de police distante, pas de CDN, décodeur
  Draco désactivé, pas d'environnement HDR téléchargé. Vérifié par le test
  Playwright (zéro requête hors réseau local).
- **Progression honnête** : une barre n'est affichée que si l'événement porte
  une progression mesurée ; sinon un indicateur d'activité. Les estimations de
  durée ne s'affichent que si l'historique local existe.
- **Visualiseur** : charge `previews/model.glb` (aperçu ≤ 250 000 faces,
  re-texturé) ; le modèle complet est chargé à la demande. Texturé non éclairé
  (les photos contiennent déjà l'éclairage réel), « sans texture » éclairé,
  filaire, nuage de points aligné (≤ 500 000 points). La miniature de la
  bibliothèque est un rendu du modèle, capturé automatiquement au premier affichage.

Règles structurantes :

1. **Le moteur ne dépend pas du serveur.** `cam3d.engine` n'importe jamais
   FastAPI ; il communique par callbacks (`StageEvent`) et fichiers. Le serveur,
   la CLI (`cam3d`) et, plus tard, les applications natives l'appellent de la
   même manière.
2. **Les outils lourds sont des processus séparés** (OpenMVS, Blender, FFmpeg),
   lancés avec `subprocess_utils.run_tool` : journal en direct, annulation,
   message d'erreur avec les dernières lignes de sortie.
3. **Les originaux ne sont jamais modifiés.** `originals/` est copié tel quel ;
   tout le travail se fait dans `processed/`.
4. **Pas de progression inventée.** Un `StageEvent.progress` n'existe que
   lorsqu'il est mesuré (image i/N, caméra i/N, carte de profondeur i/N) ;
   sinon l'UI affiche l'étape courante et un indicateur d'activité.

## Dossier projet

```
<CAM3D_DATA_DIR>/cam3d.sqlite3   index (projets, photos, tâches, appareils)
<CAM3D_DATA_DIR>/projects/<id>/
  metadata.json            copie lisible de la fiche projet (dossier autoportant)
  pipeline_result.json     résultat de la dernière reconstruction
  originals/               photos d'origine
  processed/               images de travail, database.db, sparse/, dense/, mvs/, stages/*.json
  reconstruction/          sparse.ply, dense.ply (repère OpenMVS), dense_aligned.ply (repère du modèle)
  meshes/model.obj|mtl     modèle texturé nettoyé, repère canonique (Y haut, base en y=0)
  textures/model_<i>.jpg
  previews/model.glb       aperçu navigateur (≤ 250 000 faces, re-texturé si décimé)
  previews/model_full.glb  modèle complet (seulement si l'aperçu est décimé)
  previews/pointcloud.ply  nuage dense aligné sur le modèle, ≤ 500 000 points (float32 + RGB)
  previews/thumb.jpg       miniature (photo, puis rendu 3D)
  exports/                 archives DAE/OBJ, GLB, STL, PLY, exports.json
  logs/<étape>.log, pipeline.log
```

`processed/stages/<étape>.json` permet la **reprise** (`--resume`) : une étape
terminée avec le même profil n'est pas recalculée.

## Repère et unités

- Repère interne : **Y vers le haut**, main droite, modèle centré en XZ, point le
  plus bas en y = 0. Le vecteur « haut » est estimé à partir des orientations des
  caméras (moyenne des axes −Y caméra) : fiable pour une capture à main levée.
- **Alignement « Manhattan »** : l'orientation horizontale dominante des surfaces
  verticales (murs, côtés d'un meuble) est mesurée par un histogramme pondéré par
  l'aire (modulo 90°, affiné sous le degré) et alignée sur les axes X/Z ; il n'est
  appliqué que si au moins ~20 % de l'aire des murs partage la même orientation
  au-delà du hasard. Puis un quart de tour place le côté photographié (centre moyen
  des caméras) vers **+Z** : la vue « Face » du visualiseur montre ce que
  l'utilisateur a photographié et, dans SketchUp, les murs suivent les axes rouge/vert.
- Échelle : la photogrammétrie monoculaire n'a **pas d'échelle métrique**.
  `TexturedModel.unit_scale` reste `None` tant que l'utilisateur n'a pas étalonné
  (phase 6). Les exports l'indiquent dans leur note.
- DAE : converti en **Z-up** (SketchUp) avec `<up_axis>Z_UP</up_axis>` et
  `<unit meter="1"/>`. GLB/OBJ restent Y-up (conventions glTF/OBJ).

## Choix techniques (arbitrages)

| Sujet | Décision | Pourquoi |
|---|---|---|
| SfM | `pycolmap` (wheel PyPI, CPU) plutôt que le binaire COLMAP | installable par `pip` sur Windows/macOS/Linux, API Python, pas de CUDA requis. Le binaire COLMAP reste détecté (optionnel). |
| Dense + maillage + textures | **OpenMVS 2.3.0**, CPU | COLMAP dense (PatchMatch) exige CUDA → exclu pour les machines sans NVIDIA. OpenMVS tourne sur CPU, produit directement un maillage texturé avec atlas (export GLB, relu par trimesh). |
| Version OpenMVS | 2.3.0 et non 2.4.0 | 2.4.0 exige CGAL 6 et OpenCV ≥ 4.11 (absents d'Ubuntu 24.04 / Homebrew stable). Deux correctifs source sont appliqués (voir INSTALLATION.md). |
| DAE | écrivain **pycollada** maison, pas Blender | Blender **5.x a supprimé l'import/export COLLADA** (vérifié : `bpy 5.2.3` n'a plus `collada_import`). Dépendre de Blender pour le format prioritaire était un risque ; le writer maison est léger, déterministe et testé. Blender 4.5 LTS sert uniquement à la validation. |
| Sortie de TextureMesh | **GLB** plutôt qu'OBJ | l'écrivain OBJ d'OpenMVS 2.3.0 plante sur un maillage mono-texture (binaires officiels non corrigés) ; l'écrivain glTF est fiable. `mesh_io` relit les deux. |
| Nettoyage | trimesh/Open3D en Python, par sous-ensembles de faces | conserve UV et textures sans ré-échantillonnage. |
| Filtrage géométrique | avant texturage, sur le PLY brut | les surfaces « ciel » d'OpenMVS sont supprimées avant de gaspiller l'atlas de textures. |
| Exécution des traitements | un **processus séparé** par tâche, groupe de processus dédié | un plantage natif (OpenMVS, COLMAP) ou un arrêt forcé n'affecte pas le serveur ; l'annulation tue aussi les sous-processus OpenMVS. |
| Caméra sur téléphone | HTTPS local par **autorité locale contrainte** aux adresses privées + repli `<input capture>` | les navigateurs mobiles exigent un contexte sécurisé ; aucune protection n'est contournée, l'utilisateur choisit d'installer le certificat ; sans lui, l'appareil photo natif fonctionne en HTTP. |
| Vidéo | extraction FFmpeg + sélection (netteté relative, similarité, exposition) | une vidéo n'est pas supposée meilleure que des photos : seules les images nettes et distinctes sont gardées. |
| Sécurité réseau local | appairage par code + approbation explicite sur l'ordinateur, jeton porteur | pas de compte ni de cloud ; une adresse IP du réseau local ne suffit jamais pour accéder aux projets. |
| Simplification avec textures | **après** maillage, **avant** texturage (`--target-face-num` d'OpenMVS) | décimer un maillage déjà texturé dégrade les UV. Les niveaux de simplification de « Export SketchUp » (phase 6) re-texturent un maillage décimé. |

## Licences des composants

| Composant | Licence | Mode d'utilisation | Redistribution |
|---|---|---|---|
| COLMAP / pycolmap | BSD-3-Clause | bibliothèque Python | libre |
| OpenMVS | **AGPL-3.0** | exécutable séparé (subprocess) | possible en fournissant les sources (ou lien vers les sources officielles + patches) ; cam3D ne le lie pas |
| VCGLib (dépendance OpenMVS) | GPL-3 | compilé dans OpenMVS | idem |
| Open3D | MIT | bibliothèque | libre |
| trimesh, pycollada, numpy, scipy | MIT / BSD | bibliothèques | libre |
| OpenCV (opencv-python-headless) | Apache-2.0 | bibliothèque | libre |
| FFmpeg | LGPL-2.1+ (GPL selon build) | exécutable séparé | distribuer un build LGPL ou demander l'installation |
| Blender | GPL-2+ | exécutable séparé, **optionnel** (validation) | ne pas embarquer |
| Jeu de test Sceaux Castle | © Pierre Moulon (openMVG) | tests uniquement | **non redistribué** dans le dépôt |

Conséquence : cam3D peut être distribué gratuitement ; l'installateur devra
soit faire compiler/installer OpenMVS depuis les sources officielles, soit
embarquer un binaire OpenMVS accompagné de ses sources (obligation AGPL).

## Évolutivité prévue

- Applications natives iOS/Android : même API locale (REST + WebSocket) ; la
  capture LiDAR produira des nuages/maillages importables dans `reconstruction/`.
- IA : étapes optionnelles du pipeline (segmentation de l'objet avant SfM,
  amélioration de textures) insérées comme nouvelles `stages/` sans toucher aux
  autres.
- GPU NVIDIA : `pycolmap` CUDA et OpenMVS CUDA sont détectés automatiquement
  (`hardware.has_cuda`) et utilisés quand présents, sans changer l'API.
