# Photogrammétrie — pipeline et paramètres

## Étapes

| # | Étape | Outil | Entrées → sorties | Progression |
|---|---|---|---|---|
| 1 | Préparation | Pillow / OpenCV | `originals/` → `processed/images/` (JPEG q95, EXIF orientation appliquée, redimensionnées selon le profil), `images.json` (netteté = variance du laplacien, luminosité, focale EXIF) | mesurée (image i/N) |
| 2 | Estimation des caméras (SfM) | pycolmap (COLMAP) | SIFT → appariement exhaustif (≤150 images) ou séquentiel → cartographie incrémentale → `sparse/0/` (bin + txt), `points.ply`, `sfm.json` | mesurée (caméra i/N) |
| 3 | Reconstruction dense | pycolmap `undistort_images` + OpenMVS `InterfaceCOLMAP`, `DensifyPointCloud` | `dense/` (PINHOLE) → `mvs/scene_dense.ply` | mesurée (cartes de profondeur i/N) |
| 4 | Maillage | OpenMVS `ReconstructMesh` + filtrage maison | `scene_dense_mesh.ply` → `scene_dense_mesh_filtered.ply` | activité |
| 5 | Raffinement (ULTRA) | OpenMVS `RefineMesh` | maillage raffiné photométriquement | activité |
| 6 | Texturage | OpenMVS `TextureMesh` | `textured.glb` (glTF binaire, atlas intégré) ; 3 tentatives : seam-leveling global → sans seam-leveling → maillage brut | activité |
| 7 | Nettoyage | trimesh | composants isolés, faces dégénérées, repère canonique | activité |
| 8 | Export | trimesh / pycollada | OBJ, GLB, STL, PLY, DAE | mesurée (format i/N) |

Images excluses automatiquement : netteté < 25 (variance du laplacien sur une
version 800 px), luminosité moyenne < 30 ou > 235. Si moins de 3 images
restent, toutes sont conservées (avertissement dans le journal).

## Filtrage géométrique (étape 4)

Le maillage Delaunay/graph-cut d'OpenMVS ferme les scènes non bornées par de
grandes surfaces (ciel, fond). `stages/meshfilter.py` supprime :

- les faces dont la plus longue arête dépasse 10 × l'arête médiane ;
- les faces dont le centre est à plus de 6 × l'arête médiane de tout point du
  nuage dense (surfaces sans support photogrammétrique) ;
- les composants connexes de moins de 2 % du plus grand (ou < 300 faces).

Sur le jeu Sceaux (profil RAPIDE) : 374 + 35 faces et 6 composants supprimés
sur 149 851 ; le résultat visuel passe d'un « bloc ciel » à une façade nette.

## Profils

| Paramètre | RAPIDE | HAUTE QUALITÉ | ULTRA |
|---|---|---|---|
| Taille max image (SfM/MVS) | 1600 px | 3200 px | originale |
| SIFT max features | 4096 | 8192 | 16384 |
| Appariement guidé | non | oui | oui |
| Densify `--resolution-level` / `--max-resolution` | 2 / 1200 | 1 / 2400 | 0 / 4000 |
| `--number-views-fuse` | 2 | 3 | 3 |
| `--estimate-normals` / `--filter-point-cloud` | 0 / 0 | 2 / 1 | 2 / 1 |
| `--geometric-iters` | 0 | défaut | défaut |
| ReconstructMesh `--min-point-distance` / `--smooth` | 2.5 / 2 | 2.0 / 2 | 1.5 / 1 |
| Décimation (`--target-face-num`) | 150 000 | 600 000 | aucune |
| RefineMesh | non | non | oui (niveau 1) |
| TextureMesh `--resolution-level` / atlas max | 1 / 4096 | 0 / 8192 | 0 / 8192 |

Les trois profils exécutent donc des paramètres réellement différents, à toutes
les étapes.

## Mesures (Ubuntu 24.04, 4 cœurs Xeon 2.1 GHz, 16 Go, sans GPU)

Jeu « Sceaux Castle » (11 photos 2832×2128, openMVG) :

| Profil | SfM | Dense | Maillage | Texturage | Total | Résultat |
|---|---|---|---|---|---|---|
| RAPIDE | ≈ 30 s | ≈ 40 s | ≈ 45 s | ≈ 10 s | **126 s** | 11/11 caméras, 464 k points, 149 k faces, atlas 2048² |
| HAUTE QUALITÉ | 131 s | 448 s | 79 s | 46 s | **732 s** | 11/11 caméras, 1,03 M points, 581 k faces, atlas 4096² |

Ces durées sont des mesures ; l'application n'affichera des estimations que
lorsqu'un historique local existera (phase 3).

## Limites connues et pistes

- Pas d'échelle métrique sans étalonnage (phase 6).
- L'appariement séquentiel (> 150 images) ne fait pas encore de détection de
  boucles (nécessite un arbre de vocabulaire COLMAP ; à ajouter, fichier libre
  fourni par COLMAP).
- Sans GPU, le profil ULTRA (RefineMesh CPU, pleine résolution) peut prendre
  des heures sur de grands jeux ; l'UI devra l'annoncer.
- Les objets uniformes, brillants ou transparents restent difficiles
  (limite de la photogrammétrie, pas de cam3D).
