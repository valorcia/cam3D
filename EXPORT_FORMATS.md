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

## Orientation

Avant tout export, le modèle est remis dans un repère canonique : verticale
estimée, murs dominants alignés sur les axes, côté photographié vers l'avant,
base posée au sol, centré. Dans SketchUp (Z vers le haut), la façade
photographiée fait face à l'axe vert négatif (vue « Face ») et les murs sont
parallèles aux axes rouge et vert. L'alignement n'est appliqué que si une
orientation dominante est détectée (objets organiques : seule la verticale est corrigée).

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

## Profil « Export SketchUp »

Onglet Exports › Export SketchUp, trois niveaux :

| Niveau | Faces max | Usage |
|---|---|---|
| Léger | 50 000 | tout ordinateur, maquettes d'implantation |
| Standard | 150 000 | bon compromis |
| Détaillé | 400 000 | ordinateur récent |

Étapes réellement exécutées (`engine/sketchup.py`) :

1. part du modèle **édité** courant (nettoyage, découpe, rotations) ;
2. applique l'**échelle étalonnée** (mètres) si elle existe ;
3. orientation : repère canonique (verticale, murs sur les axes, façade
   photographiée vers l'avant), écrit en **Z vers le haut** ;
4. réduit le nombre de polygones par décimation OpenMVS ;
5. **re-projette les photos** sur le maillage réduit (nouvel atlas propre, au
   lieu de déformer les UV existantes) ;
6. écrit le DAE ;
7. regroupe `.dae` + `textures/` dans `model_sketchup_<niveau>.zip` ;
8. **relit et vérifie** le DAE : axe Z, unité mètre, UV, matériaux liés,
   textures présentes et en chemins relatifs, nombre de faces. L'export échoue
   explicitement si une vérification ne passe pas.

Tous les formats (OBJ, GLB, STL, PLY, DAE) sont écrits en mètres lorsque le
modèle est étalonné ; sinon la note de l'export rappelle que l'échelle est relative.
