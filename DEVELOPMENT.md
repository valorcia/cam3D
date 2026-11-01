# Développement

## Organisation du dépôt

```
backend/            package Python `cam3d` (moteur + CLI + serveur à venir), tests pytest
  cam3d/engine/     moteur de reconstruction (aucune dépendance Web)
  cam3d/cli.py      commandes `cam3d doctor|reconstruct|export|serve`
  tests/            tests unitaires (synthétiques) + test d'intégration (photos réelles)
frontend/           interface Next.js (voir frontend/README.md)
scripts/            install.sh / install.ps1 / start.sh / build_openmvs_linux.sh, patches, validation Blender
third_party/        outils externes installés localement (ignoré par git)
```

## Environnement

```bash
./scripts/install.sh && source .venv/bin/activate
pip install -e "backend[dev]"
```

## Lancer les tests

```bash
cd backend
pytest -q -p no:dash                                   # unitaires (< 2 s)
CAM3D_TEST_DATASET=/chemin/photos pytest -q -m slow    # intégration réelle (~2-3 min, profil RAPIDE)
```

## Interface Web

```bash
cd frontend && npm ci
npm run dev            # http://localhost:3000, API sur :8765 (cam3d serve dans un autre terminal)
npm run lint && npm test
npm run build          # out/ servi par cam3d serve sur http://127.0.0.1:8765
```

Règles d'interface :

- un bouton visible fonctionne ; une fonction pas encore livrée n'a pas de bouton ;
- pas de pourcentage sans mesure (`StageView.progress` vient du moteur) ;
- aucune ressource chargée depuis Internet ;
- textes en français, cibles tactiles ≥ 40 px, navigation basse sur téléphone.

## Conventions

- Python 3.10+, typage, dataclasses pour toutes les structures échangées
  (`SfmResult`, `MeshResult`, `ExportResult`, `PipelineResult`…), sérialisables
  en JSON (`asdict`).
- Chaque étape = une fonction `run_<étape>(…, logger, cancel)` qui :
  1. appelle `logger.start()`, écrit ses journaux, `logger.progress()` uniquement
     sur une mesure réelle, `logger.finish()` ou lève une exception ;
  2. écrit ses sorties dans le dossier de travail et retourne une dataclass ;
  3. vérifie `cancel.check()` entre les sous-étapes longues.
- Les messages destinés à l'utilisateur sont en français et expliquent la
  cause probable (« trop peu de recouvrement… ») ; les journaux bruts des
  outils vont dans `logs/<étape>.log`.
- Ne jamais remplacer un résultat réel par une démonstration ; une fonction non
  disponible doit l'être explicitement (`ToolInfo.available == False`).
- Ajouter une fonctionnalité = ajouter une étape ou un module ; ne pas réécrire
  les étapes qui fonctionnent.

## Ajouter un format d'export

1. écrire `export_<fmt>(model, out_dir, name) -> ExportResult` dans
   `stages/export.py` ;
2. l'ajouter à `FORMATS` et à `run_exports` ;
3. ajouter un test dans `tests/test_export.py` qui relit le fichier produit.

## Ajouter un profil ou un paramètre

Les profils sont des `QualityProfile` figés dans `profiles.py` ; chaque champ
est consommé par une étape identifiée. Documenter le changement dans
`PHOTOGRAMMETRY.md`.

## Débogage d'un échec OpenMVS

Les commandes exactes sont dans `logs/dense.log`, `logs/mesh.log`,
`logs/texture.log` ; elles peuvent être relancées à la main dans
`processed/mvs/`. Pour un plantage natif : `gdb -q -batch -ex run -ex bt --args <commande>`.
