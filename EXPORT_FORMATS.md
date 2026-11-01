# Formats d'export

Tous les exports partent du modèle canonique `meshes/model.obj` (Y haut,
base en y = 0, échelle non étalonnée tant que `unit_scale` est absent).

| Format | Fichier produit | Géométrie | UV | Textures | Repère | Note |
|---|---|---|---|---|---|---|
| **DAE** | `exports/<nom>_dae.zip` = `<nom>.dae` + `textures/` | triangles + normales | oui (set 0) | référencées en relatif `textures/<nom>_<i>.jpg` | **Z-up**, mètres | prioritaire SketchUp |
| OBJ | `exports/<nom>_obj.zip` = `.obj` + `.mtl` + textures | v/vt/vn, f | oui | `map_Kd` relatif | Y-up | |
| GLB | `exports/<nom>.glb` | oui | oui | intégrées | Y-up (glTF) | aperçu navigateur |
| STL | `exports/<nom>.stl` (binaire) | oui | non | **non** | Y-up | note explicite : pas de textures |
| PLY | `exports/<nom>.ply` (+ `<nom>_pointcloud.ply`) | maillage binaire | non | non | Y-up | nuage dense fourni à part |

## DAE pour SketchUp — ce que contient le fichier

- `<asset>` : `<up_axis>Z_UP</up_axis>`, `<unit meter="1" name="meter"/>`,
  auteur/outil ;
- `<library_images>` : une image par texture, `init_from` relatif ;
- `<library_effects>` : effet `lambert`, `<diffuse><texture texture="…sampler" texcoord="UVSET0"/>`,
  double face ;
- `<library_geometries>` : une `<geometry>` par matériau, sources
  positions / normales / UV, un `<triangles>` avec inputs VERTEX, NORMAL, TEXCOORD set 0 ;
- `<library_visual_scenes>` : nœud racine `cam3D_model`, `instance_material`
  avec `<bind_vertex_input semantic="UVSET0" input_semantic="TEXCOORD" input_set="0"/>`.

Validation effectuée (voir TESTING.md) : relecture pycollada, `assimp info`,
import Blender 4.5.15 (UV layer présent, image trouvée, rendu Cycles).
**L'import dans SketchUp n'a pas encore été testé sur une installation réelle** ;
protocole prévu dans TESTING.md.

## Profil « Export SketchUp » (phase 6)

Étapes prévues : préparation de la géométrie, application de l'échelle
étalonnée, orientation Z-up (déjà fait), **simplification à plusieurs niveaux
en re-texturant un maillage décimé** (50 k / 150 k / 500 k faces) pour rester
fluide dans SketchUp, vérification de cohérence des chemins de textures, zip.
