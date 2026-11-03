# Feuille de route

## Phase 3 — Backend ✅ (livré)
- FastAPI : projets (CRUD, renommage, duplication, suppression, archivage), import
  de photos (validation, limites de taille), lancement/annulation/relance des
  reconstructions, journaux, exports à la demande.
- Gestionnaire de tâches : file d'attente, 1 reconstruction à la fois,
  événements WebSocket (`StageEvent`), reprise après interruption (`--resume`).
- SQLite pour les métadonnées, fichiers sur disque (`projects/`).
- Historique des durées par profil pour afficher des estimations fondées.

## Phase 4 — Interface Web ✅ (livrée)
- Next.js + TypeScript + Tailwind + Zustand ; mode sombre ; responsive.
- Tableau de bord, bibliothèque (miniatures générées à partir du GLB),
  suivi des étapes, visualiseur Three.js (texturé / sans texture / wireframe /
  nuage de points, vues ortho, grille, axes, recentrage), téléchargements.
- Aperçus allégés (GLB décimé) pour ne pas charger les modèles lourds.

## Phase 5 — Capture mobile ✅ (livrée, validation sur appareils réels en phase 7)
- PWA, caméra (`getUserMedia`), compteur, prévisualisation, suppression,
  détection de flou côté client, conseils de déplacement.
- Vidéo : extraction FFmpeg (netteté, similarité, luminosité).
- Appairage QR code + code temporaire ; **HTTPS local** avec certificat généré
  (mkcert-like) et procédure d'approbation iPhone/Android ; repli : import depuis
  la galerie.

## Phase 6 — Optimisation ✅ (livrée)
- Grandes scènes : vocabulaire visuel COLMAP (boucles + ressemblance) au-delà de 150 photos, reconstruction globale GLOMAP à partir de 300, étalonnage partagé grâce aux EXIF ; mesuré sur 329 photos (voir PHOTOGRAMMETRY.md).
- Nettoyage interactif (sélection, découpe, suppression, composants, simplification,
  recentrage/rotation/échelle, annulation, copie de l'original).
- Étalonnage (2 points + distance), unités mm/cm/m, statut d'étalonnage affiché.
- « Export SketchUp » : niveaux de simplification avec re-texturage, vérification.

## Phase 7 — Validation (✅ Linux ; reste : SketchUp, téléphones réels, Windows, macOS)
- Parcours complet téléphone → ordinateur → reconstruction → DAE → SketchUp
  sur Windows 11 et macOS ; installateurs.

## Capture à distance ✅ (livrée, testée avec un relais local)
- Scan continu (images choisies automatiquement, guidage, anneau boussole) dans cam3D Capture et dans la capture locale.
- Guide visuel façon LiDAR dans cam3D Capture (plein écran, maillage des points de l'image, zones non couvertes en bleu) : repère visuel, pas une mesure de profondeur. Pas encore dans la capture locale.
- Reste : déploiement Vercel (Blob store, variables), essai sur téléphones réels.

## Prochaines étapes prioritaires
- Valider l'import dans SketchUp (protocole dans TESTING.md) et ajuster le DAE si nécessaire.
- Valider la capture sur iPhone et Android réels (certificat, résolution).
- Valider l'installation sur Windows 11 et macOS ; installateur pour non-développeurs.
- Grandes scènes au-delà de quelques centaines de photos : découpage du nuage dense en sous-scènes (OpenMVS `--sub-scene-area`) pour borner la mémoire ; non mesuré ici.

## Plus tard
- iOS/Android natifs, LiDAR avec maillage en direct (ARKit / ARCore Depth), segmentation IA de l'objet, amélioration IA des
  textures, plans 2D, surfaces/volumes, DXF, STEP sur géométrie adaptée.
