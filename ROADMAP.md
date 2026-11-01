# Feuille de route

## Phase 3 — Backend ✅ (livré)
- FastAPI : projets (CRUD, renommage, duplication, suppression, archivage), import
  de photos (validation, limites de taille), lancement/annulation/relance des
  reconstructions, journaux, exports à la demande.
- Gestionnaire de tâches : file d'attente, 1 reconstruction à la fois,
  événements WebSocket (`StageEvent`), reprise après interruption (`--resume`).
- SQLite pour les métadonnées, fichiers sur disque (`projects/`).
- Historique des durées par profil pour afficher des estimations fondées.

## Phase 4 — Interface Web
- Next.js + TypeScript + Tailwind + Zustand ; mode sombre ; responsive.
- Tableau de bord, bibliothèque (miniatures générées à partir du GLB),
  suivi des étapes, visualiseur Three.js (texturé / sans texture / wireframe /
  nuage de points, vues ortho, grille, axes, recentrage), téléchargements.
- Aperçus allégés (GLB décimé) pour ne pas charger les modèles lourds.

## Phase 5 — Capture mobile
- PWA, caméra (`getUserMedia`), compteur, prévisualisation, suppression,
  détection de flou côté client, conseils de déplacement.
- Vidéo : extraction FFmpeg (netteté, similarité, luminosité).
- Appairage QR code + code temporaire ; **HTTPS local** avec certificat généré
  (mkcert-like) et procédure d'approbation iPhone/Android ; repli : import depuis
  la galerie.

## Phase 6 — Optimisation
- Profils déjà en place ; ajout d'un arbre de vocabulaire pour > 150 images.
- Nettoyage interactif (sélection, découpe, suppression, composants, simplification,
  recentrage/rotation/échelle, annulation, copie de l'original).
- Étalonnage (2 points + distance), unités mm/cm/m, statut d'étalonnage affiché.
- « Export SketchUp » : niveaux de simplification avec re-texturage, vérification.

## Phase 7 — Validation
- Parcours complet téléphone → ordinateur → reconstruction → DAE → SketchUp
  sur Windows 11 et macOS ; installateurs.

## Plus tard
- iOS/Android natifs, LiDAR, segmentation IA de l'objet, amélioration IA des
  textures, plans 2D, surfaces/volumes, DXF, STEP sur géométrie adaptée.
