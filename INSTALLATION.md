# Installation

> État : procédure **testée sur Ubuntu 24.04** (conteneur, 4 cœurs, 16 Go, sans GPU).
> Les procédures Windows et macOS suivent les distributions officielles mais
> **n'ont pas encore été exécutées sur une machine réelle** ; elles seront validées
> en phase 7.

## Prérequis communs

- Python ≥ 3.10 (3.13 testé)
- 8 Go de RAM minimum (16 Go recommandés), 10 Go d'espace disque libre
- Aucun GPU requis. Un GPU NVIDIA accélère COLMAP/OpenMVS s'ils sont compilés avec CUDA (non requis).

## Linux (Ubuntu 24.04)

```bash
git clone https://github.com/valorcia/cam3D && cd cam3D
./scripts/install.sh                     # venv + pip (pycolmap, open3d, trimesh, pycollada, fastapi…)
sudo ./scripts/build_openmvs_linux.sh    # OpenMVS 2.3.0 → /opt/openmvs (≈15 min sur 4 cœurs)
sudo apt install ffmpeg                  # import vidéo
source .venv/bin/activate && cam3d doctor
```

Correctifs appliqués à OpenMVS 2.3.0 (`scripts/patches/`) :

1. `openmvs-2.3.0-formattime-fortify.patch` — `Util::formatTime` passait une taille
   de tampon erronée à `snprintf` ; `_FORTIFY_SOURCE=3` (par défaut sur Ubuntu 24.04)
   abandonne le processus (`*** buffer overflow detected ***`) dès la première
   carte de profondeur.
2. `openmvs-2.3.0-saveobj-single-texture.patch` — `Mesh::SaveOBJ` lit
   `faceTexindices[i]` même quand le tableau est vide (cas une seule texture) →
   segfault à l'export OBJ. cam3D contourne aussi ce bug en demandant une sortie
   GLB à `TextureMesh`, ce qui rend les binaires officiels (Windows, Homebrew)
   utilisables sans recompilation — à confirmer en phase 7.

OpenMVS 2.4.0 a été écarté : il exige CGAL ≥ 6 et OpenCV ≥ 4.11.

## macOS

```bash
brew install python ffmpeg openmvs      # formule Homebrew officielle d'OpenMVS
./scripts/install.sh
export CAM3D_OPENMVS_DIR="$(brew --prefix)/bin"   # si cam3d doctor ne trouve pas OpenMVS
cam3d doctor
```

Point d'attention : la caméra d'un iPhone exige HTTPS (phase 5).

## Windows 11

1. Installer Python 3.11+ depuis python.org (cocher « Add to PATH »).
2. Télécharger l'archive Windows **officielle** d'OpenMVS 2.3.0
   (https://github.com/cdcseacave/openMVS/releases) et la décompresser dans
   `third_party\openmvs\` (les `.exe` doivent être dans `third_party\openmvs\bin\`),
   ou définir `CAM3D_OPENMVS_DIR`.
3. Installer FFmpeg (https://ffmpeg.org/download.html) et l'ajouter au PATH.
4. `powershell -ExecutionPolicy Bypass -File scripts\install.ps1`

`pycolmap` fournit des wheels Windows ; aucune compilation n'est nécessaire.

## Variables d'environnement

| Variable | Rôle |
|---|---|
| `CAM3D_OPENMVS_DIR` | dossier contenant `DensifyPointCloud`, `ReconstructMesh`, `TextureMesh`, `InterfaceCOLMAP` |
| `CAM3D_COLMAP` | chemin du binaire COLMAP (optionnel) |
| `CAM3D_BLENDER` | chemin de Blender (optionnel, validation DAE) |
| `CAM3D_FFMPEG` | chemin de FFmpeg |
| `CAM3D_TEST_DATASET` | dossier de photos réelles pour le test d'intégration |

## Diagnostic

`cam3d doctor` affiche OS, CPU, RAM, disque, GPU, et l'état de chaque outil ;
`cam3d doctor --json` fournit la même chose au serveur et à l'installateur.
Le diagnostic ne télécharge rien.

## Téléphone (même réseau Wi-Fi)

`cam3d serve --host 0.0.0.0` (ou `./scripts/start.sh`) sert :

- `http://<ip>:8765` : interface et API ;
- `https://<ip>:8443` : la même chose en HTTPS, nécessaire pour utiliser la
  **caméra dans le navigateur** (iOS et Android l'exigent).

Le certificat HTTPS est émis par une **autorité locale** créée au premier
démarrage dans `<CAM3D_DATA_DIR>/tls/` (clé privée lisible par l'utilisateur
seul). Elle est limitée par contraintes de noms aux adresses privées et à
`localhost`/`*.local` : installée sur un téléphone, elle ne permet pas
d'intercepter d'autres connexions. Son empreinte SHA-256 est affichée au
démarrage, dans Paramètres et sur la page d'installation du téléphone.

Parcours : Paramètres › Connecter un téléphone (ou « Capturer avec le
téléphone » dans un projet) → scanner le QR code → page d'installation :

| Choix | Ce qu'il faut faire | Capture possible |
|---|---|---|
| Connexion sécurisée (recommandé) | installer le certificat une fois (iOS : profil puis « Réglages des certificats » › activer ; Android : Paramètres › Sécurité › Installer un certificat CA) | caméra dans la page, envoi automatique photo par photo |
| Sans certificat | rien | appareil photo natif du téléphone (pleine résolution, une photo à la fois), galerie, vidéo |

Dans les deux cas l'ordinateur doit **approuver** l'appareil (code à 6 chiffres
+ bouton « Autoriser »). `cam3d serve --no-https` désactive le HTTPS local.

> Non vérifié sur de vrais téléphones dans cet environnement : le parcours a été
> testé avec Chromium en émulation Pixel 7, caméra simulée et autorité
> installée dans son magasin de confiance (voir TESTING.md). Les étapes iOS
> (profil + confiance totale) sont celles documentées par Apple et restent à
> valider sur un iPhone réel en phase 7.
