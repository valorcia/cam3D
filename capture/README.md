# cam3D Capture — capture sur téléphone, n'importe où

Application web installable (PWA) hébergée sur Vercel. Elle permet de
photographier un objet ou un lieu **sans ordinateur à proximité**, même hors
connexion. La reconstruction 3D reste faite ensuite par cam3D sur votre ordinateur.

```
Téléphone (cam3D Capture, HTTPS)          Relais (Vercel Blob)                Ordinateur (cam3D)
 photos dans IndexedDB  ──chiffrées──▶    objets chiffrés, 7 jours max  ──▶   « Depuis le téléphone »
 clé AES par scan (reste sur le tél.)      aucune clé, aucune photo en clair     téléchargement + déchiffrement
                                                                                + vérification SHA-256 → projet
 └── ou sans relais : Partager les photos (AirDrop, Quick Share) / ZIP ──────▶  import dans un projet
```

## Ce que fait l'application
- **Scan continu (mode par défaut)** : on appuie une fois, on tourne autour de
  l'objet ; le flux de la caméra est analysé ~8 fois par seconde et une image
  pleine résolution est gardée automatiquement quand elle est nette (par
  rapport aux images récentes), prise sans mouvement brusque, bien exposée et
  assez différente de la précédente. Consignes en direct (« Ralentissez »,
  « Déplacez-vous », « Image floue », « Trop sombre ») ; densité réglable
  (Léger / Normal / Dense). Un anneau montre les directions déjà couvertes et
  la hauteur (haut / milieu / bas), mesurées par la **boussole et
  l'inclinaison du téléphone** : ce n'est pas une estimation 3D.
- **Guide visuel façon LiDAR** (bouton « Guide », actif par défaut) : pendant le
  scan, l'image passe en plein écran et un maillage relie les points détectés
  dans l'image (coins, ~200 points, recalculés ~7 fois par seconde). Les zones
  dont la direction n'est pas encore couverte par une image gardée sont
  teintées en bleu ; elles s'éclaircissent quand on les capture. Quand la vue
  est couverte, une flèche indique de quel côté continuer, puis « changez de
  hauteur » une fois le tour fait. **Ce n'est pas du LiDAR ni une mesure de
  profondeur** : le maillage est en 2D sur l'image, et la couverture vient de la
  boussole, de l'inclinaison et d'un champ de vue approximatif (~50° × 64°).
  Sans capteurs d'orientation, la vue s'éclaircit juste après chaque image
  gardée puis redevient bleue.
- **Photo par photo** : déclencheur manuel, appareil photo natif, galerie.
- **Hors connexion** : l'application s'ouvre sans réseau (service worker) ; les
  photos restent sur le téléphone et partent automatiquement au retour du réseau.
- **Relais chiffré** : chaque scan a sa propre clé AES-256-GCM générée sur le
  téléphone ; le relais ne reçoit que des objets chiffrés (photos et manifeste,
  noms de fichiers compris). Le **code de transfert** contient l'adresse du
  manifeste et la clé : il se colle dans cam3D (ou s'ouvre via le lien
  `/t/#…`, le fragment `#` n'est jamais envoyé au serveur).
- **Sans relais** : partage natif des photos ou export ZIP, importables tels quels dans cam3D.
- **Effacement** : les copies chiffrées sont supprimées chaque jour au-delà de
  7 jours (Vercel Cron), ou immédiatement depuis le téléphone.

## Différence avec Polycam

Le principe du mode photo de Polycam (filmer, images choisies
automatiquement) est reproduit. Le modèle 3D construit **en direct**, point par
point, de Polycam repose sur le LiDAR et ARKit de l'iPhone Pro, inaccessibles à
une page web (Safari n'expose ni la profondeur ni ARKit) : il demande une
application iOS native (feuille de route). La reconstruction se fait ici sur
l'ordinateur, après la capture. Le guide visuel ci-dessus en reprend l'aspect pour se repérer,
sans prétendre mesurer la profondeur.

## Sécurité
| Menace | Protection |
|---|---|
| Lecture des photos sur le relais ou par Vercel | chiffrement de bout en bout, clé jamais envoyée au relais |
| Fichier remplacé ou altéré | AES-GCM authentifié, chemin de l'objet en donnée associée, SHA-256 vérifié sur le PC |
| Inconnus utilisant votre stockage | jetons d'envoi délivrés seulement avec `RELAY_ACCESS_KEY` (relais fermé si absente), objets limités à 40 Mo, chemins imposés |
| Code de transfert intercepté | le code donne accès au scan : ne l'envoyer qu'à soi-même ; scans effacés après 7 jours |
| Le PC poussé à télécharger ailleurs (SSRF) | cam3D n'accepte que `https://*.public.blob.vercel-storage.com`, sans redirection |

## Déploiement sur Vercel
1. Projet Vercel relié au dépôt avec **Root Directory = `capture`** (framework Next.js).
2. Créer un **Blob store** et le connecter au projet (ajoute `BLOB_READ_WRITE_TOKEN`).
3. Variables d'environnement : `RELAY_ACCESS_KEY` (au moins 16 caractères, à
   saisir une fois dans Réglages du téléphone) et `CRON_SECRET` (effacement quotidien).
4. Déployer ; ouvrir l'adresse sur le téléphone, « Ajouter à l'écran d'accueil ».

Si la « Deployment Protection » de Vercel est active, le téléphone doit être
connecté à votre compte Vercel pour ouvrir l'application (protection
supplémentaire) ; le relais reste de toute façon fermé sans `RELAY_ACCESS_KEY`.

## Développement et tests
```bash
npm ci
npm test                                   # chiffrement (vecteur partagé avec backend/cam3d/server/relay.py)
RELAY_STORAGE=local RELAY_ACCESS_KEY=dev-key-0123456789 npm run build && RELAY_STORAGE=local RELAY_ACCESS_KEY=dev-key-0123456789 npm start
# relais local (dossier .relay-dev) à la place de Vercel Blob ; cam3D : CAM3D_RELAY_ALLOW=http://localhost:3100
node tests/e2e_remote.mjs                  # voir l'en-tête du fichier pour les variables
```
