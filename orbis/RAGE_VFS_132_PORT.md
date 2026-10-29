# RDR2 PS4 1.32 / PS5 13.60 — adaptateur de fichiers RAGE/RPF8

État du 28 octobre 2026. Ce travail fait **une réelle substitution des octets
sur des appels VFS simulés**, et génère un **module PRX Orbis** contenant ce
moteur. Il **n'installe pas encore le hook dans le vrai processus de RDR2**.
Le module annonce explicitement GAME_HOOK_NOT_INSTALLED.

## Ce qui existe dans le code

- runtime/rage_vfs_redirect.h + .cpp : interface C/Orbis pour
  l'interception en lecture d'un fichier virtuel RAGE, avec callback de
  repli vers le mécanisme RPF8 d'origine.
- runtime/rage_vfs_harness.cpp : RPF fictif sur PC, tests de toutes les
  opérations et de la redirection d'octets.
- orbis/rage_vfs_module.c : point d'entrée de plugin Orbis ; charge
  en lecture seule overlay.map, puis attend une liaison aux fonctions
  d'origine du moteur.
- orbis/build_rage_vfs.ps1 : compilateur PS4/Orbis et contrôles des
  symboles/SELF/empreinte SHA-256.
- orbis_build/LmlBridge_132_rage_vfs_adapter.prx : module compilé,
  non vérifié dans le jeu.

## Deux voies complémentaires pour RAGE

### 1. Interception du système de fichiers RPF8 (ressources brutes)

Une fois que les méthodes réelles de fiDevice dans RDR2 1.32 auront été
localisées et vérifiées, un adaptateur spécifique au jeu doit les détourner.
Il appelera l'API du module dans cette séquence :

1. lml_rage_load_overlay(map, root) charge les entrées FileReplacement
   et vérifie la taille des fichiers locaux.
2. lml_rage_bind_game_io(ops) reçoit les trampolines **originaux**
   de RAGE, pas les points d'entrée déjà hookés.
3. Au RAGE Open/OpenBulk, lml_rage_open_file(path, mode, &token, &source)
   choisit un fichier moddé lisible ou l'ouverture d'origine.
4. Toutes les opérations de ce **token du pont** doivent être reprises par
   l'adaptateur : read_file, read_at, seek_file, size_file et close_file.
5. Les appels GetFileSize / GetFileTime / GetAttributes doivent également
   être dirigés vers lml_rage_stat_path, afin d'éviter une incohérence
   entre les métadonnées du jeu et la taille réelle du fichier moddé.

Les tokens retournés sont **différents des handles RAGE du jeu**. Le jeu ne
doit JAMAIS recevoir directement un token sans qu'un adaptateur de handles
intercepte **toutes** les opérations correspondantes. Cette condition est
obligatoire pour éviter un crash.

Un fichier absent, un remplaçant d'une taille différente de son manifeste,
ou une requête non conforme passent au lecteur d'origine. Aucun fichier
de jeu ou archive RPF8 n'est modifié sur le disque.

### 2. Redirection du chargeur XML/META/OMT/DAT (chemin)

Un appel aux chargeurs de texte RAGE peut, **si sa signature PS4 est
confirmée**, être remplacé plus directement :

- lml_rage_select_loader_path(virtual, buf, size) trouve le chemin
  physique d'un remplaçant présent, de taille correcte.
- lml_rage_dispatch_text_loader(virtual, original, ctx, request, &redirected)
  appelle exactement une fois le chargeur original, avec le chemin
  physique sélectionné, sinon avec le chemin virtuel initial.

Cette branche ne s'applique PAS aux formats binaires RAGE (.ytd, .ymt,
.ymap, .ytyp, etc.) ni aux nouveaux fichiers streaming. Le thunk doit
connaître la **vraie signature du chargeur RDR2 1.32**. Le callback original
doit consommer/copier le chemin pendant l'appel (pointeur temporaire de
pile) et ne doit pas réentrer dans le hook.

## Recherche sur les projets existants

- RageOpenRDR2 (PC, GPLv3) : prouve que les opérations OpenBulk,
  GetFileSize, GetFileTime et GetAttributes doivent rester cohérentes,
  et montre le principe du montage de devices virtuels. Ses signatures
  PC **ne sont pas des signatures de RDR2 PS4** :
  https://github.com/Chiheb-Bacha/RageOpenRDR2
- WildRAGE's (PS4, uniquement **RDR2 1.00**) : démonstration publique de
  la substitution de chemins XML/OMT/DAT dans les chargeurs PS4. Ses RVA
  1.00 et ses signatures **ne sont pas valables par défaut pour 1.32**.
  Ce projet ne vendore pas son code :
  https://github.com/rfoodxmodz/RDR2-WildRAGE-s
- LML : exemples install.xml FileReplacement / StreamingFile / DataFile.
  Nous ne modifions pas vfs.asi et ne réutilisons pas ses binaires.
- RPF8 : les tables d'archives sont chiffrées et le contenu peut être
  compressé/formaté par RAGE ; l'overlay contourne le besoin de repacker
  en agissant au niveau où RAGE connaît déjà le chemin de ressource.

## Conditions exactes pour ACTIVER le hook sur RDR2 1.32

Il manque un **eboot.bin/ELF PS4 1.32 lisible** (issu de la propre copie
du jeu), un Title ID CUSA spécifique, ainsi qu'un test loader réussi sur
la PS5 13.60.

La validation doit permettre de déterminer :
1. La vraie adresse et signature de fiDevice Open/OpenBulk et des méthodes
   correspondantes, OU la signature de l'un des chargeurs XML/META de 1.32.
2. L'ABI (registres, arguments, retours, durée des pointeurs, handles).
3. Les premiers octets du point d'entrée à préserver dans le trampoline,
   vérifiés contre un fingerprint de l'ELF et le Title ID.
4. Un mécanisme de hook réversible fourni par le chargeur PS4, qui ne
   modifie rien si le hash de version ou les octets attendus ne correspondent
   pas. Ne pas copier les offsets connus pour le jeu 1.00.
5. La lecture du chemin /data/etaHEN/lml_bridge depuis le sandbox du jeu.
6. La validation d'un unique remplacement non critique et réellement
   compatible avec le format attendu par le jeu, en mode Histoire hors ligne.

Aucun eboot PS4 1.32 n'a été trouvé dans le dossier modloader fourni.
Ce module reste donc un composant de liaison : installer le PRX seul ne
remplacera **aucun fichier** du vrai jeu.

## Statut des formats des exemples LML

- FileReplacement : 8 correspondances préparées hors ligne. Le moteur de
  lecture de remplacement est implémenté, mais pas relié à fiDevice 1.32.
- StreamingFile : 2 fichiers, **enregistrement dans le streamer manquant**.
- DataFile : 4 déclarations, **registration du type de données manquante**.
- Ressources dans les 14 fichiers : 9 fichiers XML dans des extensions
  binaires RAGE, 3 fichiers .meta XML, 1 gxt2 texte et 1 RSC8 binaire.
  Les données XML de ressources RAGE ne sont pas sérialisées en PSO :
  un remplacement brut pourrait être rejeté par le moteur.

## Compilations et tests sur le PC

Depuis le dossier modloader :

    powershell -NoProfile -ExecutionPolicy Bypass -File .\ps4_lml_bridge\orbis\build_rage_vfs.ps1
    python -B -m unittest discover -s .\ps4_lml_bridge\tests -p test_*.py -v

Les tests reproduisent une demande update:/common/data/ai/combatbehaviour.meta
avec MODDED_CONTENT et un jeu fictif qui retournerait ORIGINAL_CONTENT.
Ils vérifient notamment les données redirigées, les offsets, les tailles,
le fallback, les métadonnées, les handles et l'absence d'écrasement des
binaires du jeu.

Pas de test console, pas de validation du hook réel, pas de conversion
généralisée d'ASI Windows vers Orbis.
