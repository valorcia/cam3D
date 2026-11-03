# Photogrammétrie — pipeline et paramètres

## Étapes

| # | Étape | Outil | Entrées → sorties | Progression |
|---|---|---|---|---|
| 1 | Préparation | Pillow / OpenCV | `originals/` → `processed/images/` (JPEG q95, EXIF orientation appliquée, redimensionnées selon le profil ; marque, modèle et focale EXIF conservés pour COLMAP, rien d'autre — ni GPS ni date), `images.json` (netteté = variance du laplacien, luminosité, focale EXIF) | mesurée (image i/N) |
| 2 | Estimation des caméras (SfM) | pycolmap (COLMAP / GLOMAP) | SIFT → appariement exhaustif (≤ 150 images) ou séquentiel + boucles + ressemblance (> 150, voir « Grandes scènes ») → cartographie incrémentale (globale GLOMAP à partir de 300 images) → `sparse/0/` (bin + txt), `points.ply`, `sfm.json` | mesurée (caméra i/N) ; non détaillée en mode global |
| 3 | Reconstruction dense | pycolmap `undistort_images` + OpenMVS `InterfaceCOLMAP`, `DensifyPointCloud` | `dense/` (PINHOLE) → `mvs/scene_dense.ply` | mesurée (cartes de profondeur i/N) |
| 4 | Maillage | OpenMVS `ReconstructMesh` + filtrage maison | `scene_dense_mesh.ply` → `scene_dense_mesh_filtered.ply` | activité |
| 5 | Raffinement (ULTRA) | OpenMVS `RefineMesh` | maillage raffiné photométriquement | activité |
| 6 | Texturage | OpenMVS `TextureMesh` | `textured.glb` (glTF binaire, atlas intégré) ; 3 tentatives : seam-leveling global → sans seam-leveling → maillage brut | activité |
| 7 | Nettoyage et aperçus | trimesh / Open3D / OpenMVS | composants isolés, faces dégénérées, repère canonique (verticale, murs alignés, face vers +Z), aperçu ≤ 250 k faces re-texturé, nuage aligné | activité |
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

## Grandes scènes (plusieurs centaines de photos)

| Nombre de photos | Appariement | Reconstruction des caméras |
|---|---|---|
| ≤ 150 | exhaustif (toutes les paires) | incrémentale |
| 151 à 299 | séquentiel (10 voisines dans l'ordre de prise de vue) + détection de boucles + ressemblance visuelle (30 plus proches) | incrémentale |
| ≥ 300 | idem | globale (GLOMAP, intégré à COLMAP 4) |

- **Ressemblance visuelle et boucles** : vocabulaire visuel COLMAP (fichier
  gratuit, ~72 Mo, vérifié par SHA-256, `cam3d fetch-models`). Il retrouve les
  photos d'un même endroit prises à des moments différents (retour au point
  de départ, imports dans le désordre). Sans lui : séquentiel seul, signalé.
- **Étalonnage partagé** : la marque, le modèle et la focale EXIF sont gardés
  dans les copies de travail ; les photos d'un même appareil partagent un
  étalonnage (une caméra par orientation) au lieu d'un étalonnage estimé
  séparément pour chaque photo, avec une focale de départ correcte.
- Paramètres modifiables par profil : `matching` (`auto`, `exhaustive`,
  `sequential`, `vocabtree`) et `mapper` (`auto`, `incremental`, `global`).

Mesures (4 cœurs CPU, sans GPU, profil RAPIDE : images 1 600 px, 4 096 points
SIFT) sur « Person Hall » (COLMAP, bâtiment photographié en entier, 21 Mpx) :

| Jeu | Version | Caméras | Points 3D | Erreur | Durée SfM |
|---|---|---|---|---|---|
| 165 photos | avant (EXIF perdu, séquentiel sans boucles) | 165/165 (165 étalonnages, focale par défaut 1 920 px) | 52 835 | 0,54 px | 392 s |
| 165 photos | après (EXIF, séquentiel + boucles + ressemblance) | 165/165 (2 étalonnages, focale 1 094 px) | 58 514 | 0,61 px | 531 s |
| 329 photos | après, reconstruction globale | 329/329 | 121 589 | 0,67 px | 1 414 s ¹ |
| 329 photos | après, reconstruction incrémentale (pour comparer) | 329/329 | 124 076 | 0,65 px | 1 507 s |

¹ Une autre reconstruction tournait en même temps pendant ~4 min : durée majorée.

À 329 photos, les deux méthodes donnent la même qualité ; l'étape de
reconstruction des caméras prend ~8 min en global (malgré la charge en plus)
contre 11,4 min en incrémental. L'écart doit grandir avec le nombre de photos
(l'incrémental refait des ajustements de plus en plus gros) : non mesuré ici
au-delà de 329.

La durée SfM inclut l'extraction des points (~5,5 min pour 329 photos) et
l'appariement (~10 min).

**Maillage des grandes scènes.** Les budgets de faces des profils sont pensés
pour un objet (~60 photos). Ils sont maintenant multipliés par
`nombre de photos / 60` (au plus ×8 ; ULTRA reste sans décimation), et
l'espacement des points insérés dans le maillage (`--min-point-distance`) est
augmenté si la mémoire estimée dépasse 80 % de la mémoire disponible
(estimation tirée de la mesure ci-dessous : ~3,2 Ko par sommet de la
tétraédrisation). Si ReconstructMesh échoue quand même (manque de mémoire),
il est relancé avec des points deux fois plus espacés (2 fois au plus).

Chaîne complète RAPIDE sur les 329 photos (même machine, 16 Go) :

| Étape | Avant | Après (budget adapté) |
|---|---|---|
| Caméras | 329/329, 121 841 points, 0,68 px | identique |
| Nuage dense | 15 726 000 points | identique |
| Maillage brut (ReconstructMesh) | 5 640 363 faces | — |
| Maillage conservé | **132 887 faces** (plafond 150 000) | **730 583 faces** (budget 822 000), espacement 2,58 px au lieu de 2,5 |
| Texture | 1 atlas 4096² | 2 atlas 4096² |
| Pic de mémoire (maillage) | ~13,2 Go | ~9,7 Go |
| Durée | 65 min au total | maillage + texture 13,4 min au lieu de ~9 |

Rendu : avec le budget adapté, briques, encadrements de fenêtres, banc et
massifs sont lisibles ; avant, toit déchiqueté et façades lisses. Les profils
HAUTE QUALITÉ et ULTRA n'ont **pas** été mesurés sur ce jeu : leur nuage dense
serait ~4× plus grand, l'espacement des points serait alors augmenté pour tenir
en mémoire sur 16 Go.

## Limites connues et pistes

- Pas d'échelle métrique sans étalonnage (phase 6).
- Grandes scènes : voir ci-dessous ; la reconstruction dense et le maillage
  d'une scène de plusieurs centaines de photos restent longs sur CPU.
- Sans GPU, le profil ULTRA (RefineMesh CPU, pleine résolution) peut prendre
  des heures sur de grands jeux ; l'UI devra l'annoncer.
- Les objets uniformes, brillants ou transparents restent difficiles
  (limite de la photogrammétrie, pas de cam3D).

## Édition non destructive, étalonnage

- L'original reconstruit est copié dans `meshes/original/` (plus l'aperçu et les
  nuages de points d'origine) et n'est **jamais** modifié. Les modifications
  sont une liste d'opérations (`processed/edits.json`) rejouée sur l'original :
  annuler = retirer la dernière, revenir à l'original = liste vide (confirmation).
- Opérations : découpe par boîte, effacement d'une zone tracée à l'écran (à
  travers toute la profondeur), suppression des parties isolées, rotation de
  90°, recentrage, simplification. Elles sont exprimées géométriquement dans le
  repère du modèle : la même liste s'applique au modèle complet, à l'aperçu et
  aux nuages de points.
- La liste n'est enregistrée qu'après succès : une opération qui viderait le
  modèle échoue sans rien modifier.
- **Simplification** : décimation OpenMVS puis **re-texturage depuis les
  photos** (la géométrie est ramenée dans le repère de reconstruction en
  composant la transformation canonique et les rotations d'édition). Résultat
  mis en cache. Mesure : 580 573 → 100 000 faces en 42 s (profil HAUTE QUALITÉ),
  rejoué depuis le cache en 5 s.
- **Étalonnage** : deux points + distance connue (mm, cm, m) → mètres par
  unité, stocké dans `processed/calibration.json` (méthode « manuelle »). Les
  modifications rigides ne changent pas les distances, l'étalonnage reste
  valable. Une nouvelle reconstruction l'efface (nouvelle échelle). Statuts
  affichés : non étalonné, étalonné manuellement, étalonné avec une source de
  référence (réservé aux futures sources : LiDAR, mire). Une distance non
  étalonnée est toujours affichée « u (non étalonné) ».
- Toute modification ou tout changement d'étalonnage supprime les exports
  existants (fichiers dérivés, régénérables) pour éviter des fichiers périmés.
