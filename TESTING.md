# Tests

## Tests unitaires (synthétiques, rapides)

`cd backend && pytest -q -p no:dash` — 13 tests, < 2 s :

- profils distincts, erreurs sur profil inconnu ;
- détection matérielle et découverte d'outils sans exception ;
- aller-retour OBJ et GLB (UV, textures, chemins relatifs) ;
- transformation avec réflexion (inversion de l'ordre des sommets) ;
- rotation « haut → +Y », repère canonique (base en y = 0, centré) ;
- suppression des composants isolés **sur positions fusionnées** (les coutures
  UV dupliquent les sommets) ;
- écrivain DAE : Z_UP, unité mètre, UV set 0, normales, `UVSET0`, texture
  relative existante, `assimp info` ;
- exports des 5 formats (zips contenant textures, GLB rechargé avec texture) ;
- préparation : exclusion d'une image floue, fichiers non image ignorés.

## Test d'intégration (photos réelles)

`CAM3D_TEST_DATASET=<dossier> pytest -q -m slow` exécute le pipeline complet
(profil RAPIDE) et vérifie : succès, ≥ 80 % de caméras enregistrées,
> 10 000 faces, textures présentes, zip DAE avec `textures/`, aperçu GLB,
événements de progression bornés dans [0, 1].

Jeu utilisé : « Sceaux Castle » (openMVG, 11 photos, © Pierre Moulon) — utilisé
uniquement pour les tests, non redistribué.

## Résultats mesurés (1er novembre 2026, Ubuntu 24.04, 4 cœurs, 16 Go, sans GPU)

| Vérification | Résultat |
|---|---|
| SfM : caméras enregistrées | 11 / 11, 5 174 points, erreur de reprojection 0,43 px |
| Dense (RAPIDE) | 464 379 points |
| Maillage | 149 851 faces → 148 943 après filtrage |
| Texturage | 1 atlas 2048×2048 (GLB OpenMVS → JPEG q95) |
| Pipeline complet RAPIDE (`cam3d reconstruct`) | **succès en 126 s**, 5 exports |
| Test d'intégration `pytest -m slow` (RAPIDE, sortie GLB + filtrage + nettoyage) | **réussi** en 206 s |
| Pipeline complet HAUTE QUALITÉ | **succès en 732 s** : 1 030 021 points denses, 580 573 faces, atlas 4096² ; DAE importé dans Blender 4.5 sans erreur |
| DAE relu par pycollada | Z_UP, 1 m, 1 jeu UV, normales, image présente |
| DAE lu par Assimp 5.3 | 1 maillage, 149 591 faces, 1 matériau |
| DAE importé dans Blender 4.5.15 (module `bpy`) | 1 objet, UV layer, matériau avec image 2048² trouvée, bbox Z 0→6,45 ; rendu Cycles : façade texturée reconnaissable |
| Blender 5.2.3 | **pas d'importateur COLLADA** (supprimé) — ne pas s'appuyer sur Blender 5 pour le DAE |
| SketchUp | **non testé** (pas d'installation disponible dans cet environnement) |

## Protocole de validation manuelle SketchUp (à exécuter sur un poste réel)

1. Décompresser `exports/model_dae.zip` dans un dossier vide.
2. SketchUp → Fichier → Importer → type COLLADA (`.dae`) ; options : « Fusionner
   les faces coplanaires » décoché, « Valider le fichier » coché.
3. Vérifier : le modèle est debout (Z haut), les textures s'affichent
   (Style « Texturé ombré »), le nombre de faces est raisonnable (< 500 k),
   le modèle est à l'origine, base au sol.
4. Mesurer une distance connue avec l'outil Mètre et comparer (échelle
   non étalonnée attendue tant que la phase 6 n'est pas livrée).
5. Consigner la version de SketchUp, la durée d'import et tout avertissement.

## Script de validation Blender

```
/opt/cam3d-bpy/bin/python scripts/blender/validate_dae.py -- model.dae report.json render.png
# ou : blender -b --python scripts/blender/validate_dae.py -- model.dae report.json render.png
```

Le script importe le DAE, contrôle UV/matériaux/images, écrit un rapport JSON et
rend une vue Cycles CPU pour contrôle visuel. Il nécessite Blender ≤ 4.5.
