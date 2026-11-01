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
