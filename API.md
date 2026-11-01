# API locale (FastAPI)

Démarrage : `cam3d serve --host 0.0.0.0 --port 8765` (ou `./scripts/start.sh`).
Documentation interactive générée : `http://127.0.0.1:8765/docs`.
Les données sont stockées dans `CAM3D_DATA_DIR` (défaut `~/cam3D`) :
`cam3d.sqlite3` (index) et `projects/<id>/` (fichiers, `metadata.json`).

## Autorisations

| Client | Droits |
|---|---|
| Cet ordinateur (adresse de bouclage) | tout |
| Appareil appairé (jeton `Authorization: Bearer …` ou `?token=` pour WebSocket/images) | tout sauf : suppression de projet, appairage, gestion des appareils |
| Autre | `/api/health`, `/api/pair/claim`, `/api/pair/requests/{id}` uniquement |

Appairage (`GET /api/whoami` sert de sonde : rôle `desktop`, `device` ou `anonymous`, toujours en 200) :

1. ordinateur : `POST /api/pair/sessions?next=/capture/?id=…` → `{code, urls[] (page d'installation HTTP), https_urls[], secure, expires_at}` (QR : `GET /api/pair/qr.svg?url=…`) ;
2. téléphone : `POST /api/pair/claim {code, device_name}` → `{request_id, secret}` ;
3. ordinateur : `GET /api/pair/pending`, puis `POST /api/pair/requests/{id}/approve` (ou `/reject`) ;
4. téléphone : `GET /api/pair/requests/{id}?secret=…` → `{status:"approved", token}` (remis une seule fois).

Un code sert à un seul appareil, expire après 10 min et se bloque après 5 erreurs.
Les jetons sont stockés hachés (SHA-256) et expirent après 7 jours ; révocation :
`DELETE /api/devices/{id}`.

## Projets et photos

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/api/projects?archived=false` | bibliothèque (nom, date, état, nb photos, faces, taille) |
| POST | `/api/projects {name}` | créer |
| GET | `/api/projects/{id}` | détail + photos + exports + tâche active + estimations |
| PATCH | `/api/projects/{id} {name?, archived?}` | renommer / archiver |
| POST | `/api/projects/{id}/duplicate` | dupliquer |
| DELETE | `/api/projects/{id}?confirm=true` | supprimer (ordinateur uniquement, confirmation obligatoire) |
| POST | `/api/projects/{id}/photos` (multipart `files`) | ajouter des photos ; réponse `{added[], rejected[]}` |
| GET/DELETE | `/api/projects/{id}/photos/{name}` (`?thumb=true`) | voir / retirer une photo |
| GET/PUT | `/api/projects/{id}/thumbnail.jpg` | miniature (PUT : capture 3D envoyée par l'UI) |
| GET | `/api/projects/{id}/preview.glb` | modèle texturé pour le visualiseur |
| GET | `/api/projects/{id}/pointcloud.ply?kind=sparse|dense` | nuage de points |

Validation des photos : extension (JPEG, PNG, HEIC*, WebP, TIFF), décodage réel
de l'image, taille ≤ `CAM3D_MAX_PHOTO_MB` (60 Mo), résolution ≥ 640×480, nom
assaini (ASCII, sans chemin), jamais d'écrasement. Netteté et luminosité sont
mesurées et renvoyées en avertissements (`floue`, `trop sombre`, `surexposée`).
\*HEIC nécessite `pillow-heif` ; sinon un message demande le réglage « Le plus compatible ».

## HTTPS local et vidéo

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/api/tls` | public : HTTPS actif, ports, empreinte de l'autorité locale |
| GET | `/api/tls/ca.crt` | public : certificat de l'autorité locale (à installer sur le téléphone) |
| POST | `/api/projects/{id}/video` (multipart `file`) | vidéo ≤ `CAM3D_MAX_VIDEO_MB` (2 Go) ; tâche `video` : extraction FFmpeg, images nettes et distinctes ajoutées au projet ; la vidéo originale est conservée dans `originals/videos/` |

## Import depuis cam3D Capture

| Méthode | Route | Rôle |
|---|---|---|
| POST | `/api/relay/import {code, project_id?}` | crée un projet (ou complète `project_id`) et lance la tâche `relay` : téléchargement depuis Vercel Blob, déchiffrement, vérification, import |
| POST | `/api/projects/{id}/photos` avec un `.zip` | importe les photos d'une archive (exportée du téléphone), noms aplatis, tailles vérifiées |

`CAM3D_RELAY_ALLOW=http://localhost:3100` autorise un relais de développement ;
sinon seules les adresses `https://*.public.blob.vercel-storage.com` sont acceptées.

## Édition et étalonnage

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/api/projects/{id}/edits` | liste des opérations appliquées |
| POST | `/api/projects/{id}/edits {op}` | ajoute une opération (tâche `edit`, enregistrée seulement si elle réussit) |
| POST | `/api/projects/{id}/edits/undo` | retire la dernière opération |
| POST | `/api/projects/{id}/edits/reset?confirm=true` | revient à l'original |
| PUT | `/api/projects/{id}/calibration {p1, p2, distance, unit}` | étalonnage manuel (unit : mm, cm, m) |
| DELETE | `/api/projects/{id}/calibration` | retire l'étalonnage |
| POST | `/api/projects/{id}/exports {sketchup_level}` | profil Export SketchUp : `light`, `standard`, `detailed` |

Opérations : `{"type":"crop_box","min":[x,y,z],"max":[x,y,z]}`,
`{"type":"delete_region","matrix":[16 valeurs, vue×projection three.js],"polygon":[[x,y] NDC]}`,
`{"type":"remove_components","min_fraction":0.05}`, `{"type":"rotate","axis":"y","degrees":90}`,
`{"type":"recenter"}`, `{"type":"simplify","target_faces":100000}`.

## Traitements

| Méthode | Route | Rôle |
|---|---|---|
| POST | `/api/projects/{id}/reconstruct {profile, formats[], resume}` | mettre en file (202) |
| POST | `/api/projects/{id}/exports {formats[]}` | ré-exporter le modèle existant |
| GET | `/api/projects/{id}/jobs`, `/api/jobs`, `/api/jobs/{id}` | état, étape courante, événements |
| POST | `/api/jobs/{id}/cancel` | annulation (douce, puis arrêt forcé après 15 s) |
| POST | `/api/jobs/{id}/retry` | relance avec reprise des étapes terminées |
| GET | `/api/estimate?profile=&images=` | estimation **uniquement** si un historique existe sur cet ordinateur, sinon `null` |
| GET | `/api/projects/{id}/logs`, `/logs/{étape}?tail=400` | journaux |
| GET | `/api/projects/{id}/exports`, `/exports/{fichier}` | liste / téléchargement |
| WS | `/api/events` | `job_queued`, `job_started`, `job_event` (étape, statut, message, progression mesurée), `job_cancelling`, `job_finished`, `ping` |

États d'un projet : `empty`, `ready`, `queued`, `processing`, `done`, `failed`,
`cancelled`, `interrupted`. États d'une tâche : `queued`, `running`,
`succeeded`, `failed`, `cancelled`, `interrupted`.

Une seule reconstruction s'exécute à la fois ; chacune tourne dans un
processus séparé (`python -m cam3d.worker`) : un plantage natif d'OpenMVS ou
COLMAP fait échouer la tâche, jamais le serveur.
