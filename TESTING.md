# Tests

## Validation complète (phase 7)

`scripts/validate_all.sh <photos> [video.mp4 camera.y4m]` rejoue tout : tests
moteur et API, intégration sur photos réelles, typage et tests de l'interface,
puis les trois scénarios navigateur sur un serveur temporaire.

Exécution du 1er novembre 2026 sur un **clone neuf** du dépôt GitHub, installé
par `scripts/install.sh` (2 min 49) avec OpenMVS compilé par
`scripts/build_openmvs_linux.sh` (correctifs appliqués automatiquement) :

| Bloc | Résultat |
|---|---|
| Tests moteur + API | 43 réussis |
| Intégration photos réelles (pipeline complet) | réussi, 2 min 45 |
| Interface : TypeScript + vitest | 9 réussis |
| Parcours complet (`e2e.mjs`) | 11/11 |
| Édition, étalonnage, Export SketchUp (`e2e_edit.mjs`) | 8/8 |
| Capture mobile HTTPS, repli HTTP, vidéo (`e2e_capture.mjs`) | 10/10 ; 15/15 caméras pour les photos prises dans le navigateur |
| **Bilan** | **TOUT A RÉUSSI** |

Cette validation sur clone neuf a révélé deux défauts invisibles dans le dossier
de développement, tous deux corrigés : la page Bibliothèque n'était pas
versionnée (motif `projects/` du `.gitignore` trop large) et la détection des
outils laissait des journaux OpenMVS dans le dossier courant.

### Ce qui reste à valider hors de cet environnement

| Élément | Raison | Protocole |
|---|---|---|
| Import dans **SketchUp** | pas d'installation SketchUp ici | « Protocole de validation manuelle SketchUp » ci-dessous |
| **iPhone** et **Android** réels | émulation Chromium seulement | installer le certificat (INSTALLATION.md), capturer 30 photos d'un objet, reconstruire, noter la résolution obtenue |
| **Windows 11** et **macOS** | environnement Linux seulement | `install.ps1` / `install.sh`, `cam3d doctor`, puis `validate_all.sh` |
| GPU NVIDIA (CUDA) | pas de GPU ici | vérifier la détection dans `cam3d doctor` et les durées |


## Tests unitaires (synthétiques, rapides)

`cd backend && pytest -q -p no:dash` — 40 tests moteur + API, < 30 s. Moteur :

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
- préparation : exclusion d'une image floue, fichiers non image ignorés ;
- alignement des murs sur les axes et face photographiée vers +Z (boîte tournée de 30°) ;
- sorties de texturage jamais confondues avec le maillage d'entrée ; nuage de points compact relu par Open3D.

## Tests de l'API (`tests/test_server.py`, < 10 s)

Exécutés contre l'application FastAPI réelle (TestClient) avec une base SQLite
et un dossier de données temporaires :

- CRUD projets : arborescence créée, `metadata.json`, renommage, duplication,
  archivage, suppression avec confirmation obligatoire, identifiants malformés ;
- validation des envois : image valide, nom dangereux assaini, image floue
  acceptée avec avertissement, faux JPEG, PDF, résolution trop faible, fichier
  trop gros, noms en double jamais écrasés ;
- appairage : refus sans jeton, code faux, code réutilisé, approbation
  explicite, jeton remis une seule fois, suppression interdite au téléphone,
  révocation, rejet ;
- tâches : < 3 photos refusé, succès avec événements WebSocket, échec puis
  relance avec reprise, plantage du worker signalé sans affecter le serveur,
  annulation douce, arrêt forcé d'un worker qui ignore l'annulation, file
  d'attente une tâche à la fois, tâches interrompues marquées au redémarrage,
  estimation absente sans historique ;
- export par le **vrai** worker (`python -m cam3d.worker export`) : zips DAE/OBJ,
  STL sans texture, téléchargement, protection contre la traversée de chemin.

Les tests de tâches utilisent `tests/stub_worker.py`, un double de test qui
parle le protocole du worker (millisecondes au lieu de minutes). Il n'est
jamais utilisé par l'application. La reconstruction réelle via l'API est
vérifiée par l'essai HTTP ci-dessous.

## Essai HTTP de bout en bout (serveur réel)

Serveur `cam3d serve --host 0.0.0.0` ; « téléphone » simulé en joignant
l'adresse réseau local de la machine (donc traité comme appareil distant).
Résultats du 1er novembre 2026 :

| Étape | Résultat |
|---|---|
| Accès sans jeton | 401 |
| Appairage : code → demande en attente → approbation sur l'ordinateur → jeton | OK |
| Envoi des 11 photos (25 Mo) | 200, 11 acceptées, 1,8 s |
| Estimation avant tout historique | `null` (aucune durée inventée) |
| Reconstruction RAPIDE suivie par WebSocket | succès, 48 événements, 8 étapes |
| Modèle | 149 001 faces, 16,9 Mo (maillage + textures) |
| `preview.glb` / `model_dae.zip` | 200 ; zip = `model.dae` + `textures/model_0.jpg` |
| Estimation après 1 reconstruction | 149 s pour 11 images, fondée sur 1 exécution mesurée |
| Suppression demandée par le téléphone | 403 (réservée à l'ordinateur) |

Ce même essai a révélé que le jeton du WebSocket apparaissait dans le journal
d'accès d'uvicorn : corrigé (cookie HttpOnly + masquage `token=`/`secret=`,
testé par `test_log_filter_redacts_tokens`).

## Interface Web

- `npm test` (vitest) : formatage, repli des événements en étapes (aucun
  pourcentage sans mesure), conseils d'échec.
- `npm run lint` : vérification TypeScript stricte.
- `node tests/e2e.mjs` (Playwright + Chromium, serveur réel, reconstruction
  réelle). Dernière exécution le 1er novembre 2026, **11/11 scénarios réussis** :

| Scénario | Durée |
|---|---|
| Accueil : actions, état du moteur (WebSocket connecté) | 0,8 s |
| Nouveau scan + import des 11 photos réelles par le sélecteur de fichiers | 1,4 s |
| Rejet d'un faux JPEG avec message clair | < 0,1 s |
| Reconstruction RAPIDE lancée depuis l'interface, 8 étapes suivies jusqu'à « Exportation » terminée ; aucune estimation affichée sans historique | 151 s |
| Visualiseur : modèle chargé, rendu WebGL non vide ; modes texturé, sans texture, filaire, nuage ; ortho face et dessus | 11 s |
| Miniature 3D enregistrée automatiquement | — |
| Téléchargement du ZIP SketchUp : `model.dae` + `textures/` ; génération d'un STL à la demande | 1,9 s |
| Bibliothèque : carte avec miniature, 11 photos, « Modèle prêt », taille | 0,3 s |
| Paramètres : diagnostic matériel et moteurs | 0,2 s |
| Téléphone (profil Pixel 7, adresse réseau local) : redirection vers l'appairage, code saisi, demande approuvée sur l'ordinateur, bibliothèque et modèle 3D visibles, suppression refusée (403) | 6,6 s |
| Aucune requête hors réseau local, aucune erreur console | — |

Les captures d'écran sont produites dans `tests/screenshots/` (non versionnées).
Ces tests ont révélé et fait corriger : une bascule d'onglet automatique
déroutante, un rendu 3D continu (3 cœurs CPU en rendu logiciel, batterie des
téléphones), et un alignement des murs non appliqué sur un scan réel (seuil de
confiance trop strict).

Le DAE téléchargé par l'interface a ensuite été importé dans Blender 4.5 :
148 769 faces, UV présentes, texture 2048² trouvée, emprise X ±5,26, Y ±2,34,
Z 0→6,21 : modèle posé au sol, façade parallèle à l'axe X, tournée vers −Y
(vue « Face » de SketchUp).

## Capture mobile (`frontend/tests/e2e_capture.mjs`)

Chromium en émulation **Pixel 7**, caméra simulée alimentée par une vidéo des
photos du château (`--use-file-for-fake-video-capture`), autorité locale ajoutée
au magasin de confiance NSS du navigateur (simule un téléphone qui a installé
le certificat). Les erreurs HTTPS ne sont **pas** ignorées. Résultat du
1er novembre 2026 : **9/9 scénarios réussis**.

| Scénario | Résultat |
|---|---|
| QR → page d'installation en HTTP, certificat téléchargeable, lien HTTPS | OK |
| Bascule en HTTPS de confiance (`isSecureContext` vrai) | OK |
| Appairage approuvé sur l'ordinateur, redirection vers la capture | OK |
| 16 photos prises dans le navigateur, envoyées automatiquement une à une | 16/16 en 25 s |
| Suppression d'une photo depuis la bande de capture (aussi sur l'ordinateur) | OK |
| Reconstruction des 15 photos prises dans le navigateur | **15/15 caméras**, 0,29 px, 149 423 faces, 120 s |
| Repli HTTP sans certificat : champ `capture="environment"` (appareil photo natif), galerie | OK |
| Import vidéo depuis l'interface de l'ordinateur | 11 images extraites |
| Aucune erreur console sur le téléphone | OK |

Tests Python associés : import vidéo réel avec FFmpeg (4 vues distinctes, une
image floue et des passages immobiles → exactement 4 images nettes retenues),
chaîne TLS vérifiée par OpenSSL, sonde `whoami` anonyme.

Ce qui n'a **pas** pu être testé ici : un iPhone et un téléphone Android réels
(installation du certificat, résolution réelle de `takePhoto()` / du flux vidéo,
Safari iOS). La résolution des photos prises dans le navigateur dépend de
l'appareil : Chrome Android utilise `ImageCapture.takePhoto()` (capteur complet) ;
Safari iOS ne l'implémente pas et capture le flux vidéo (souvent 1920×1080 à
4K). L'appareil photo natif (repli) donne toujours la pleine résolution.

Les tests ont révélé et fait corriger : une tâche vidéo publiée « réussie »
avant l'import de ses images, une image floue conservée au détriment de la
version nette de la même vue, et des erreurs 401 parasites avant appairage.

## Scan continu (mode par défaut de la prise de vue)

Sélection automatique d'images testée en unitaire (`autoCapture.test.ts`, dans
`capture/` et `frontend/`) : une image par nouvelle vue, rien quand le
téléphone est immobile, rejet des mouvements trop rapides, du flou, des images
sombres ou surexposées, changement d'exposition non confondu avec un
déplacement, anneau de couverture (tour complet, sauts > 45°, bandes de hauteur).

Validation du 2 novembre 2026 (`scripts/validate_all.sh`, tous les blocs verts
après correction d'un test) : caméra simulée montrant les 11 photos du château
2 s chacune, boussole simulée faisant un tour complet.

| Scénario | Images retenues | Reconstruction |
|---|---|---|
| cam3D Capture (n'importe où, relais chiffré) | 14, consignes « Déplacez-vous » / « Ralentissez » affichées, anneau à 360° | 16/16 caméras (avec 2 photos manuelles hors connexion) |
| Capture locale (même Wi-Fi, HTTPS) | 13 | 13/13 caméras, 0,33 px |

Bug trouvé : sur Chrome, seul l'événement de boussole « absolu » était écouté ;
un téléphone ne fournissant que l'orientation relative n'aurait jamais affiché
l'anneau. Les deux sont maintenant écoutés.

Non vérifiable ici : le comportement avec un vrai téléphone en mouvement
(réglage des seuils de sélection, boussole réelle, résolution du flux vidéo).

### Écran noir de la caméra (signalé le 2 novembre 2026 sur l'application en ligne)

Non reproduit dans Chromium (iPhone 13 émulé, processeur ralenti ×6, ancienne
et nouvelle version). Correctifs défensifs :
- le flux est branché sur l'élément vidéo une fois celui-ci rendu (et non
  dans une frame d'animation qui pouvait le précéder) ;
- garde-fou : sans image au bout de 4 s, nouvel essai en 1920×1440 puis avec
  les réglages par défaut ; ensuite message explicite, bouton « Réessayer » et
  appareil photo natif ; la résolution réelle s'affiche dans le viseur.
Le test « caméra qui ne renvoie aucune image » a révélé que le garde-fou ne
se réarmait pas quand la caméra redémarrait vite (états regroupés par React) :
corrigé, message affiché après 13 s. À confirmer sur l'appareil concerné.

## Capture à distance (`capture/tests/e2e_remote.mjs`)

Application cam3D Capture en production locale (`next start`, relais local à la
place de Vercel Blob), cam3D sur l'ordinateur, Chromium en émulation Pixel 7
avec caméra simulée. 2 novembre 2026, **12/12 scénarios réussis** :

| Scénario | Résultat |
|---|---|
| Clé du relais : mauvaise clé refusée, bonne clé acceptée | OK |
| Scan continu à la caméra, images envoyées chiffrées automatiquement | 15 images, 35 s |
| Guide visuel pendant le scan : plein écran, maillage des points de l'image, vue couverte après le tour | 201 points, 100 % |
| Le relais ne contient que des objets `C3D1` chiffrés, ni JPEG ni nom de fichier en clair | OK |
| Hors connexion : 2 photos de plus, application rechargée sans réseau (service worker), photos toujours là | OK |
| Retour du réseau : envoi automatique des 2 photos en attente | OK |
| Ordinateur : lien `/t/#code` → cam3D local → import ; code retiré de la barre d'adresse | 14 photos |
| Reconstruction des photos prises à distance | **17/17 caméras**, 0,34 px |
| Sans relais : ZIP exporté du téléphone importé dans un projet | 14 photos |
| Retrait immédiat du relais depuis le téléphone | OK |
| Application passée en arrière-plan : caméra libérée, rouverte au retour, aucun flux micro demandé | OK (2 novembre) |
| Aucune erreur console hors période sans réseau | OK |

Tests associés : `capture` (vitest, 15 tests, dont chiffrement : vecteur commun avec Python,
mauvaise clé, fichier interverti, altération, code de transfert ; guide : points
trouvés aux coins d'un damier et aucun sur une image unie ou un simple bord,
maillage couvrant toute l'image, couverture des directions autour du nord,
côté à continuer, tour complet) et
`backend/tests/test_relay.py` (4 tests : vecteur commun, hôtes autorisés et
refus SSRF, import vérifié à l'octet près, fichier altéré et mauvaise clé
refusés, ZIP avec chemins piégés).

Bugs trouvés par ces tests et corrigés : un contrôle du relais échoué hors
connexion restait mémorisé et bloquait tout envoi au retour du réseau ; le
retrait d'un scan du relais était annulé par la synchronisation suivante ; les
routes API redirigeaient (barre oblique finale), ce que le PC refuse ; le
plein écran du scan était 16 px trop court (marge héritée de la page).

**Non testé ici** : le vrai Vercel Blob (nécessite la création du stockage sur
votre compte) et de vrais téléphones.

## Édition, mesures, Export SketchUp (`frontend/tests/e2e_edit.mjs`)

Sur un projet réellement reconstruit (15 photos prises dans le navigateur),
1er novembre 2026, **8/8 scénarios réussis** :

| Scénario | Résultat |
|---|---|
| Mesure avant étalonnage : affichée « … u (non étalonné) » | OK |
| Étalonnage manuel (2 points touchés sur le modèle + 1000 cm), statut « Étalonné manuellement », mesure suivante en cm | OK |
| Découpe par boîte (curseur Y max) : moins de faces, entrée dans l'historique | 30 s |
| Rectangle tracé à l'écran : aperçu rouge des faces visées, effacement | 11 s |
| Rotation 90° puis annulation : historique revenu à 2 opérations | 16 s |
| Aperçu après édition toujours texturé (image présente dans le GLB) | OK |
| Export SketchUp « Léger » : vérification automatique OK, « mètres (étalonné) », ZIP téléchargé | 9 s |
| Aucune erreur console | OK |

Le ZIP téléchargé s'importe dans Blender 4.5 : 49 999 faces, UV, texture présente.
Sur le projet HAUTE QUALITÉ : rotation + découpe + simplification à 100 000
faces re-texturée (42 s), export SketchUp Léger (49 998 faces, 11 s) ; dans
Blender, la texture re-projetée correspond exactement à la géométrie.

Tests Python associés (`test_edit.py`, `test_server.py`) : validation des
opérations, découpe, effacement par rectangle projeté, rotations sans
déformation, nuage de points suivant les mêmes transformations, opération
destructrice refusée sans être enregistrée, annulation, confirmation de
réinitialisation, original jamais modifié, étalonnage appliqué aux exports DAE
et STL (dimensions vérifiées), exports supprimés quand l'étalonnage change.

**Bug trouvé et corrigé** : trimesh refuse les textures référencées par
`../textures/…` et renvoyait silencieusement un modèle sans image ; tout
traitement relisant `meshes/model.obj` (ré-exports, édition, SketchUp) perdait
la texture. Le chargeur résout désormais `map_Kd` lui-même ; deux tests, qui
échouent sur l'ancienne version, l'exigent.

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
