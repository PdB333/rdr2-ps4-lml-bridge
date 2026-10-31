# Validation réelle sur PS5 13.40 / RDR2 PS4 CUSA08519 v01.00

## RÉSOLU (31 octobre 2026, seconde session) : correspondance positive EBOOT ↔ RAM

**Cause du mismatch : erreur de traduction d'adresses dans le comparateur, pas
un mauvais EBOOT.** L'EBOOT est `ET_SCE_EXEC_ASLR` (`0xFE10`) : ses `PT_LOAD`
ont des `p_vaddr` qui commencent à 0. Les « RVA » du profil sont donc relatives
à la base d'image. L'ancien script supposait des adresses déjà absolues liées à
`0x00400000` (bias = 0) et lisait `0 + RVA` au lieu de `base + RVA`.

Carte réelle (CMD_PROC_MAPS, PID du test) — l'image est découpée en **quatre
régions contiguës nommées `executable`** ; l'ancien outil n'en voyait qu'une :

| Région | Prot | Contenu |
|---|---|---|
| `0x00400000–0x06814000` | r-x | text + rodata (nom RTTI, code) |
| `0x06814000–0x06B90000` | r-- | RELRO (vtables, typeinfo) |
| `0x06B90000–0x06E20000` | rw- | data |
| `0x06E20000–0x08A38000` | rw- | bss (registre candidat `base+0x08053D40`) |

**Formule démontrée : adresse runtime = `image_base` + RVA du profil, avec
`image_base` = début de la première région r-x `executable` (`0x00400000`
observé).** Exemple : vtable `fiPackfile8` = `0x06AB00F8` (région RELRO),
`Open` = `0x0492A480`.

Résultat de `tools/ps5debug_ng_rdr2_100_live_profile.py` corrigé (mêmes 8
lectures bornées, 1 005 octets, aucune écriture) : **exit 0**, nom RTTI,
en-tête vtable, borne de fin, 5 slots, empreinte FNV des 112 méthodes
(`8eaecb696678dad0`) et 4 prologues de code : **tous conformes**.
Un test préalable de 85 octets (nom RTTI, en-tête, slots 0–3, prologue Open)
avait donné la même conclusion.

`CMD_PROC_READ` (`<IQI` pid/adresse/longueur, statut puis données brutes) est
donc validé empiriquement : les octets reçus sont identiques au fichier.

Ce qui reste **non démontré** : SHA-256 de l'image complète en RAM ; stabilité
de la base `0x00400000` à chaque lancement (le code la relit à chaque fois, sans
la coder en dur) ; lecture directe des `p_vaddr` du fichier par cette session
(EBOOT absent de la machine — la cohérence des 112 pointeurs l'implique) ;
chargement du PRX ; tout hook. **Aucun hook n'est installé.**

### Suite (même jour) : registre et étude de chargement PRX

- **Registre `fiCollection` validé en lecture seule** :
  `tools/ps5debug_ng_rdr2_100_registry_probe.py` (exit 0) — 63 `fiPackfile8`
  bien indexés sur 64 objets ; slot 0 = `rage::pgRawStreamer`.
- Étude du chargement du PRX : `orbis/PRX_LOADING_STUDY_100.md`. Bloquant
  principal : l'adresse de `sceKernelLoadStartModule` doit être tirée de la
  table d'imports de l'EBOOT privé (absent de ce PC), puis lue en RAM.
  Aucune écriture effectuée.


## Synthèse du test sur console (31 octobre 2026)

Le propriétaire a confirmé la configuration actuelle :

- PS5 **firmware système 13.40**, via **Y2JB + Kstuff Lite +
  ShadowMountPlus** ; pas d'etaHEN.
- ps5debug-NG **v1.3.2**, capability 1.1, relié au PC Windows par
  **Tailscale**. Aucun port Internet ouvert ou transfert de console.
- RDR2 **PS4 CUSA08519**, version de l'application **01.00**, détecté
  au premier plan via CMD_PROC_LIST et CMD_CONSOLE_FOREGROUND.
- **Ne PAS publier l'adresse IP Tailscale de la console ou celle du PC**.
  Le PID est temporaire et peut changer à chaque lancement.

Sources indépendantes confirmant CUSA08519 comme RDR2 PS4 Europe :
https://serialstation.com/titles/CUSA/08519

**Mise à jour du 31 octobre 2026 — nouvelle confirmation
explicite du propriétaire : le fichier EBOOT privé analysé provient
exactement de CETTE installation CUSA08519/01.00.** Ne pas présumer
qu'il a envoyé le jeu d'une autre région, d'une autre mise à jour
ou d'une autre édition. Le contrôle des octets du processus
continue d'échouer, ce qui pointe désormais en priorité vers
un problème non résolu de traduction des adresses virtuelles ELF
vers la mémoire chargée, de segmentation/relocation ou de lecture
du processus. Ces causes sont des hypothèses, pas des preuves.

Le profil EBOOT précédemment fourni (SHA-256
e3ae087f833b0f30f462bb7f880dd2955bf9f51dbb6e56706ee9bda81581feff)
repose sur une **analyse statique de ce fichier personnel**.
Sa provenance du jeu lancé est affirmée par son propriétaire ;
le SHA-256 de l'image exécutable complète en mémoire n'a pas été
établi, et **le calcul d'adresses du comparateur live reste à auditer**.
Lire en priorité `HANDOFF_NEXT_AI.md` avant d'inférer des RVA.

## Ce qui a été effectué en lecture seule

- tools/ps5debug_ng_probe.py : branding, firmware et vérification de
  route réseau (Tailscale opt-in).
- tools/ps5debug_ng_rdr2_identity.py : liste limitée des processus,
  PID/CUSA/version de l'application en cours, validation de 01.00/1.00.
- tools/ps5debug_ng_rdr2_maps.py : carte des régions (CMD_PROC_MAPS).
  Le processus comptait lors du test environ 10 000 régions ; l'une
  est nommée "executable" et commence à l'adresse liée 0x00400000.
  Le simple début de cette région ne prouve PAS la base de chargement
  de l'EBOOT analysé.
- tools/ps5debug_ng_rdr2_100_live_profile.py : huit lectures bornées
  via CMD_PROC_READ, **au total 1 005 octets**. Les adresses sont
  choisies UNIQUEMENT depuis le profil statique connu de 1.00,
  à condition d'appartenir à la région principale lisible/exécutable.
  Aucun dump de l'EBOOT, aucun scan de mémoire étendu, aucun
  breakpoint, aucune écriture ni injection.

## Résultat critique : SIGNATURES LIVE INCOMPATIBLES

Les contrôles de l'exécutable chargé ont échoué aux RVAs attendues
pour le profil fiPackfile8 original :

- Nom de type RTTI **différent**, malgré la présence de données
  mémoire non nulles à l'adresse lue.
- En-tête de vtable **différent** : la région à l'ancienne adresse
  ne contient pas l'offset-to-top/RTTI attendus.
- 112 pointeurs virtuels **différents** (l'empreinte statique
  8eaecb696678dad0 n'est pas retrouvée).
- Préfixes de code aux quatre RVAs candidats **différents**.
- L'observation de données mémoire non nulles écarte la simple
  hypothèse selon laquelle toutes les lectures auraient répondu
  des zéros.

**Conséquence : il est INTERDIT d'installer le hook fiPackfile8 de
l'ancien EBOOT sur le processus en cours.** Le mécanisme de
préflight a correctement refusé la signature. Aucun module PRX n'a
été installé dans RDR2 et aucun des hooks n'est actif.

Cela ne prouve pas que le jeu tourne en version 1.32 : les
métadonnées indiquent **01.00**. Le propriétaire ayant confirmé que le fichier EBOOT provient
exactement du jeu lancé, **rechercher d'abord une erreur de base,
d'offset, de traduction des segments ELF vers la RAM ou du chemin de
lecture en mémoire**, sans supposer une autre édition.
On ne doit PAS inventer une nouvelle base ou appliquer de correction
d'adresses par simple soustraction.

## Étapes techniques obligatoires avant un hook réel

1. Vérifier l'origine **CUSA08519** et le hash du EBOOT déchiffré
   correspondant exactement au jeu présent sur la console.
2. Dans l'EBOOT exact, analyser le type RAGE fiPackfile8, la table
   virtuelle, les noms RTTI et les ABIs. Comparer ces signatures
   avec un jeu lancé, **uniquement en lecture bornée**.
3. Etablir les RVA du vrai profil CUSA08519 v01.00 en séparant
   les bases d'images des adresses virtuelles et en vérifiant
   les protections mémoire et les emplacements de chaque méthode.
4. Vérifier que le PRX passif peut être chargé sur le processus
   PS4 depuis la configuration Y2JB 13.40 avant une activation.
5. Préparer un hook actif seulement après une identification
   complète du moteur, du cycle de vie de l'objet, et des ABIs
   Open/Read/ReadBulk/Seek/Size/Close ; ne pas inventer de handles
   RPF8 ou lancer des patches sur les signatures non vérifiées.

Les deux scripts officiels de diagnostic n'envoient que les opcodes
autorisés en lecture : CMD_PROC_LIST, CMD_CONSOLE_FOREGROUND,
CMD_PROC_MAPS et huit CMD_PROC_READ bornés. Les scripts publies
ne contiennent aucune adresse IP de la console, aucune sauvegarde,
aucun dump, aucune chaine de code proprietaire extraite.
