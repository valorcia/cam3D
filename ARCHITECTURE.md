# Architecture

## Vue d'ensemble

```
smartphone (PWA) ──HTTPS local──▶ backend/cam3d/server  (FastAPI, phase 3)
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
                               frontend/ (Next.js + Three.js, phase 4)
```

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
projects/<id>/
  metadata.json            (géré par le serveur, phase 3)
  pipeline_result.json     résultat de la dernière reconstruction
  originals/               photos d'origine
  processed/               images de travail, database.db, sparse/, dense/, mvs/, stages/*.json
  reconstruction/          sparse.ply, dense.ply
  meshes/model.obj|mtl     modèle texturé nettoyé, repère canonique (Y haut, base en y=0)
  textures/model_<i>.jpg
  previews/model.glb       aperçu navigateur
  exports/                 archives DAE/OBJ, GLB, STL, PLY, exports.json
  logs/<étape>.log, pipeline.log
```

`processed/stages/<étape>.json` permet la **reprise** (`--resume`) : une étape
terminée avec le même profil n'est pas recalculée.

## Repère et unités

- Repère interne : **Y vers le haut**, main droite, modèle centré en XZ, point le
  plus bas en y = 0. Le vecteur « haut » est estimé à partir des orientations des
  caméras (moyenne des axes −Y caméra) : fiable pour une capture à main levée.
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
