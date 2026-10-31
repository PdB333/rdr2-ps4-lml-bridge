# Reprise par une autre IA — RDR2 PS4 1.00 / PS5 13.40 / LML Bridge

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

### En-têtes de segments lus directement dans l'EBOOT (SHA-256 vérifié)

| PT | p_offset | p_vaddr | p_filesz | p_memsz | Runtime (base 0x00400000) |
|---|---|---|---|---|---|
| LOAD r-x | 0x4000 | 0x0 | 0x6413B30 | 0x6413B30 | 0x00400000–0x06814000 |
| SCE_RELRO r-- | 0x6418000 | 0x6414000 | 0x37A130 | 0x37C000 | 0x06814000–0x06B90000 |
| LOAD rw- | 0x6794000 | 0x6790000 | 0x28E5B0 | 0x1EA7825 | 0x06B90000–0x08A38000 |

`e_type = 0xFE10`, `e_entry = 0x80`. Le départ des `p_vaddr` à 0 est donc
démontré, et les quatre régions `executable` en RAM correspondent exactement
aux segments (data + bss découpés en deux régions rw-).

### Suite (même jour) : registre et étude de chargement PRX

- **Registre `fiCollection` validé en lecture seule** :
  `tools/ps5debug_ng_rdr2_100_registry_probe.py` (exit 0) — 63 `fiPackfile8`
  bien indexés sur 64 objets ; slot 0 = `rage::pgRawStreamer`.
- Étude du chargement du PRX : `orbis/PRX_LOADING_STUDY_100.md`. Bloquant
  principal : l'adresse de `sceKernelLoadStartModule` doit être tirée de la
  table d'imports de l'EBOOT privé (absent de ce PC), puis lue en RAM.
  Aucune écriture effectuée.


**Dernière synthèse : 31 octobre 2026.**
**Dépôt public :** https://github.com/PdB333/rdr2-ps4-lml-bridge
**Commit de départ confirmé avant ce handoff :** `b2e43930116e3271417918ddac5b0fe1aaef0ec7` (branche `main`).

> **Information décisive ajoutée par le propriétaire APRÈS les précédents diagnostics : l'`eboot.bin` fourni à la première IA vient exactement de la même installation de RDR2 PS4 `CUSA08519`, version `01.00`, que celle lancée sur la PS5.**
>
> La différence de signatures constatée en mémoire doit donc être investiguée **en priorité comme une erreur de traduction fichier ELF ↔ mémoire, de base virtuelle, de structure des segments, de lecture/processus, ou une autre anomalie technique**. Ne pas partir du principe que l'utilisateur a envoyé un EBOOT d'une autre édition. Sa provenance est affirmée par l'utilisateur, pas encore prouvée indépendamment par un hash du processus entier ; ces deux niveaux de preuve doivent rester distincts.

## 1. Objectif et machine

- **Objectif final :** modloader de type Lenny's Mod Loader (LML) pour **Red Dead Redemption 2, version PS4 exécutée sur une PS5 jailbreakée**, utilisant des remplacements de ressources via le moteur RAGE/RPF8. Priorité **version PS4 1.00** ; prise en charge **1.32 seulement après**, avec profil/versionnement séparés.
- **PS5 : firmware système 13.40**, confirmé sur écran par le propriétaire et par ps5debug-NG (ne pas confondre avec version *du jeu* 1.00).
- **Jailbreak :** Y2JB, Kstuff Lite, ShadowMountPlus (nom exact à vérifier), Payload Manager. **PAS etaHEN** ; ne pas utiliser le dossier `/data/etaHEN/game_plugins/` sur cette console et ne pas lancer etaHEN par-dessus Kstuff.
- **Debugger réseau :** ps5debug-NG v1.3.2, capability 1.1, serveur de commandes TCP **744**, accessible depuis le PC Windows via **Tailscale**. L'adresse IP est privée et doit être demandée au propriétaire ou récupérée sur son poste, **jamais publiée sur le GitHub public**. Aucun port ne doit être ouvert sur Internet.
- **Jeu lancé lors du diagnostic :** titre PS4 `CUSA08519` (RDR2 Europe), `APP_VER = 01.00`, `eboot.bin` au premier plan. **PID 120 lors du test uniquement** (ne pas supposer qu'il persiste au prochain lancement).
- **PC projet :** Windows, dossier `code_src_scripthook/modloader/ps4_lml_bridge` dans le workspace local. Les outils du projet peuvent être utilisés depuis la racine du dépôt. Si l'autre IA ne dispose pas des connexions/workspace de la première IA, **elle doit cloner GitHub et se faire fournir séparément l'EBOOT privé et l'accès PC/PS5** ; un dépôt public n'accorde aucun accès automatique aux équipements.

## 2. Ce qui fonctionne réellement et ce qui ne fonctionne PAS

| Élément | État vérifié |
|---|---|
| Analyse **statique** de l'EBOOT utilisateur (121 670 745 octets) | OK, extraction RTTI et vtable fiPackfile8, vérifiée hors console |
| Compilation OpenOrbis du module PRX de trace 1.00 | OK, 13 exports, SELF/PRX local |
| Moteur de remplacement générique RAGE VFS et tests hôtes | OK sur simulateur (aucun hook dans RDR2) |
| Trace Open par *shadow vtable* d'un objet simulé | OK sur PC, originales préservées, tests concurrence/exceptions/détachement |
| Suite du dépôt (`python -B -m unittest discover -s tests -p "test_*.py" -q`) | **117 tests réussis** au dernier contrôle |
| Connectivité Tailscale Windows → ps5debug-NG PS5 13.40 | OK, vrais appels protocole en lecture seule |
| Jeu RDR2 CUSA08519/01.00 et PID au premier plan | OK, vrais appels d'identification |
| Carte des régions mémoire RDR2 | OK, métadonnées seules |
| **Correspondance des adresses RTTI/vtable de l'ancien EBOOT avec la RAM du vrai jeu** | **NON : vérification échouée. Problème bloquant.** |
| Chargement du PRX dans le processus réel RDR2 | **PAS TESTÉ** |
| Hook RAGE actif dans RDR2 / remplacement effectif RPF8 | **NON, NE PAS PRÉTENDRE LE CONTRAIRE** |
| Portage PS4 1.32 | NON, hors priorité |

## 3. EBOOT EXACT fourni précédemment

Le propriétaire l'a confirmé comme venant **de cette installation CUSA08519/01.00** :

- Nom : `eboot.bin`, **121 670 745 octets**, ELF64 Orbis, type `0xFE10`, 11 *program headers*.
- SHA-256 : `e3ae087f833b0f30f462bb7f880dd2955bf9f51dbb6e56706ee9bda81581feff`.
- **Le fichier n'est pas publié dans GitHub et ne doit jamais y être ajouté.** Il était fourni comme pièce jointe à la première conversation. La nouvelle IA doit demander qu'on lui fournisse ce même fichier directement dans son environnement (ou son chemin privé).
- Analyse statique antérieure, **à revalider en RAM** :
  - `rage::fiPackfile8` : vtable RVA supposée `0x066B00F8`, 112 slots ; type RTTI `0x066B0480`, nom RTTI `0x05D7DE40`.
  - Empreinte FNV-1a64 des 112 pointeurs virtuels normalisés : `0x8EAECB696678DAD0`.
  - Slot 2 `Open` : `0x0452A480`.
  - Slot 6 `OpenBulk` candidat : `0x0452A780`.
  - Slot 13 `Read` candidat : `0x0452B9D0`.
  - Slot 14 `ReadBulk` candidat : `0x0452BA60`.
  - Slot 19 `Close` candidat : `0x0452BE00`.
  - Registre d'instances `0x08053D40`, **hypothèse** issue du destructeur, non démontrée sur console.
  - `fiDeviceLocal::Open` candidat : `0x04533960`.
- Ne pas considérer automatiquement ces RVA comme des adresses mémoire absolues. Leur origine est l'analyse ELF privée. **L'hypothèse du calcul d'adresse par le script de comparaison est suspecte et doit être auditée**.

Fichiers à lire :
`orbis/EBOOT_RAGE_VFS_PROFILE.md`,
`tools/inspect_rdr2_eboot.py`,
`tools/verify_eboot_100.py`,
`runtime/rage_eboot_profile.c` et `.h`.

## 4. Résultats réels sur PS5, déjà effectués

Le 31 octobre 2026, sans écriture ni injection :

1. `tools/ps5debug_ng_probe.py` : identité `ps5debug-NG by OSR v1.3.2`, firmware **13.40**, OK.
2. `tools/ps5debug_ng_rdr2_identity.py` : `eboot.bin`, **PID 120 (éphémère)**, `CUSA08519`, `01.00`. Le PID au premier plan appartient à la liste de processus.
3. `tools/ps5debug_ng_rdr2_maps.py` : **9 970 régions** mémoire, **60 exécutables**. Une région nommée `executable`, `start=0x00400000`, `end=0x06814000`. **Ce seul fait ne prouve pas `image_bias=0` ni la correspondance avec les `p_vaddr` ELF**.
4. `tools/ps5debug_ng_rdr2_100_live_profile.py` a supposé `bias=start-0x00400000=0` et lu en tout **1 005 octets**, en **huit lectures de longueurs bornées** : nom type RTTI (21), en-tête vtable (16), 112 pointeurs (896), frontière (8), quatre préfixes de code (4×16). **Tout est non conforme** au fichier analysé : RTTI, header, FNV/vtable, cinq slots connus et préfixes d'entrée. Les octets lus étaient **non nuls**. Aucune action de hook n'a été lancée.
5. C'est un échec de **la comparaison à des adresses supposées**, pas une preuve que le propriétaire s'est trompé d'EBOOT. Sa confirmation explicite du même EBOOT est désormais connue.

Les résultats complets sans contenu propriétaire sont dans :
`orbis/PS5DEBUG_NG_RDR2_100_LIVE_STATUS.md`.

**Ne pas utiliser les adresses candidates du point 3 pour modifier la RAM avant d'avoir compris cet écart.**

## 5. Hypothèses techniques à vérifier en priorité

Privilégier une démarche analytique **sans changer le jeu en cours** :

1. **Reproduire l'ELF virtuel à partir des program headers** : lire `e_entry`, `p_vaddr`, `p_offset`, `p_filesz`, `p_memsz`, `p_align` et permissions. Distinguer offset **fichier**, adresse virtuelle ELF, "RVA" arbitraire, base réelle, relocations et éventuelles translations pour l'exécution d'un jeu PS4 sur PS5.
2. **Auditer le code de traduction du précédent inspecteur et le calcul `bias=0`**. Vérifier comment les méthodes `Image.rva_offset` de `tools/inspect_rdr2_eboot.py` traduisent les positions. Le fait qu'une région commence à `0x00400000` ne garantit pas que `0x05D7DE40` et `0x0452A480` y correspondent comme imaginé.
3. **Établir une correspondance positive de quelques octets uniquement**, avec le consentement du propriétaire et après nouvelle identification du PID : choisir des signatures d'entrée ELF/code **non ambigües**, vérifier dans quels segments *PT_LOAD* et régions runtime elles sont réellement mappées. Ne pas rechercher la RTTI en scannant des gigaoctets à l'aveugle. Comparer localement au même fichier propriétaire, jamais dans un dépôt public.
4. **Auditer ps5debug-NG `CMD_PROC_READ` et les offsets/ABI** à partir du code amont (`debugger/source/proc.c`, `PROTOCOL.md`) : le backend peut renvoyer une réponse positive même si une sous-lecture mémoire est incorrecte, ou les régions VM peuvent représenter autre chose que prévu. Ne pas déduire une nouvelle adresse de quelques octets de données "plausibles".
5. **Tester la stabilité au prochain lancement** : PID change, le mapping aussi peut changer. Vérifier le vrai module avant chaque expérimentation. Si besoin d'un hash complet RAM, concevoir un plan sûr et justifier le volume ; pas de dump par défaut.
6. **Conserver le fail-closed** : un décalage ou une signature incomplète ne justifie **aucune écriture**. Documenter exactement la résolution des RVA, les signatures correspondantes et les tests positifs/négatifs avant envisager un hook.

> Prochaine tâche la plus utile à la nouvelle IA : **expliquer pourquoi les octets ELF statiques ne sont pas aux adresses RAM attendues, alors que le propriétaire affirme que c'est bien le même EBOOT**, par une comparaison segment ↔ mémoire soigneuse et reproductible.

## 6. Connexion et commandes de diagnostic

Le PC et la PS5 communiquent sur le **tailnet privé du propriétaire**, sans ouvrir le port TCP 744 sur Internet. Dans le dépôt public, ne jamais inscrire les IP privées. La commande utilise l'adresse Tailscale réelle, connue du propriétaire :

```powershell
cd <DOSSIER_WINDOWS_PS4_LML_BRIDGE>
python -B .\tools\ps5debug_ng_probe.py --ip <IP_PS5_TAILSCALE> --tailscale --expected-fw 13.40
python -B .\tools\ps5debug_ng_rdr2_identity.py --ip <IP_PS5_TAILSCALE> --tailscale --expected-fw 13.40
python -B .\tools\ps5debug_ng_rdr2_maps.py --ip <IP_PS5_TAILSCALE> --tailscale --expected-fw 13.40
python -B .\tools\ps5debug_ng_rdr2_100_live_profile.py --ip <IP_PS5_TAILSCALE> --tailscale --expected-fw 13.40
```

La dernière commande renvoie **exit code 4** si le profil ne correspond pas ; c'est **normal et sûr actuellement**. Ne pas la remplacer par un hook. Les commandes dépendent de la présence de ps5debug-NG et, pour les trois dernières, de **RDR2 lancé au premier plan**.

Protocoles déjà implémentés :
- En-tête `<III` little-endian : magic `0xFFAABBCC`, opcode, taille.
- Branding `0xBD000501`, firmware `0xBD000500`.
- Liste des processus `0xBDAA0001`.
- Informations du jeu au premier plan `0xBDDD0006`.
- Maps VM `0xBDAA0004`.
- Lectures bornées `0xBDAA0002`.
- Vérifier les formats de réponse (certaines métadonnées n'ont pas de code de statut). Voir la **source officielle ps5debug-NG**, ne pas se baser uniquement sur de vieux snippets.

**NE PAS** envoyer `CMD_PROC_WRITE`, `DEBUG_ATTACH`, d'appel distant, de patch mémoire, de breakpoint ni d'injection via ce handoff.

## 7. Source et binaires compilés

Les fichiers du dépôt les plus importants sont :

- `runtime/rage_vfs_redirect.h/.cpp` : bridge RAGE VFS générique et appels d'original simulés sur PC (redirection/fallback).
- `runtime/rdr2_100_pack_trace.h/.cpp` : prototype d'interception d'`Open` via vtable privée d'instance, CAS atomique, original appelé, tests host. **Ne pas activer** tant que profil live discordant.
- `runtime/rdr2_100_registry.h/.c` : sonde bornée de registre supposé, en lecture seule.
- `runtime/rage_eboot_profile.h/.c` : garde-fou statique 1.00 strict (refuse 1.32).
- `orbis/pack_trace_100_module.c`, `orbis/build_pack_trace_100.ps1` : PRX diagnostic **passif** au démarrage.
- `orbis/RDR2_PS4_100_TRACE_STATUS.md` : risques de cycle de vie et limites des hooks.
- `tools/ps5debug_ng_*.py`, `tests/test_ps5debug_ng_*.py` : protocoles et tests PS5 en lecture seule.
- `tests/test_rdr2_100_trace.cpp` : tests d'appels concurrentiels et de retour à l'original.
- `AGENTS.md`, `PORTING_STATUS.md`, `README.md` : contexte général, parfois historique. **Ce fichier de handoff et le rapport live prévalent en cas de contradiction.**

**Sur le PC du propriétaire**, dans le dossier du projet (NON dans GitHub) :
- `orbis_build/LmlBridge_RDR2_PS4_100_fiPackfile8_trace.prx` — **532 304 octets** ; SHA-256 `1baefea5254f3c21d45c6389287bece9198e3c742c38f3e2d7d3a7c887ac3e8a`. Module passif, aucune activation automatique, **jamais testé chargé en jeu**.
- `LML_BRIDGE_RDR2_PS4_100_PS5_FW1340_DEVKIT.zip` — **367 643 octets**, archive locale avec sources et PRX ; SHA-256 `dfbbf882ba9d07f11879e16a8256c27844b8dd44ed9771ff7249b493398c2660`. Ce kit **n'établit pas la compatibilité en mémoire** du profil.
- Toolchains locales : `.toolchains/OpenOrbis/PS4Toolchain`, `.toolchains/llvm18-minimal`, GCC Strawberry Windows, Python 3.

Compilation/vérification depuis la racine du dossier :
```powershell
python -B -m unittest discover -s .\tests -p "test_*.py" -q
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\verify_pack_trace_100.ps1
python -B .\tools\verify_eboot_100.py <CHEMIN_PRIVE_EBOOT_100.bin>
```
Le dernier script nécessite de disposer du **véritable EBOOT**, hors GitHub. Une nouvelle machine peut ne pas avoir le SDK OpenOrbis ni les binaires générés ; la suite des tests peut alors avoir des skips/failures d'environnement à documenter honnêtement.

## 8. Stratégie ultérieure pour un vrai modloader

Seulement **après** correction du mismatch en RAM et validation sur console :

1. Confirmer que le chargeur Y2JB / Kstuff Lite permet de charger un PRX PS4 dans le **processus RDR2**, sans supposer qu'un payload ELF PS5 lancé depuis le Payload Manager réalise cela automatiquement. ps5debug-NG est un débogueur, **pas un installeur de plugins PRX prêt à l'emploi**.
2. Tester le PRX de diagnostic **passif**, isolément. Le journal attendu, s'il est capturé, est `[LML-100-TRACE] MODULE_ENTRY PS4-1.00; PASSIVE_NO_GAME_HOOK`.
3. Ne mettre en place un traceur `Open` qu'avec vtable/ABI et durée de vie du `fiPackfile8` **démontrées**, sur un seul objet, synchronisation moteur garantie.
4. Une trace `Open` **n'est pas** un remplacement de ressource. Pour retourner des handles synthétiques, toutes les opérations utiles (`Read`, `Seek`, `Size`, `Stat`, `Close`, `OpenBulk`, etc.) doivent être interceptées de façon cohérente. Sinon conserver le **handle natif**. Tester un fichier non critique hors ligne ; maintenir rollback immédiat.
5. Les fichiers XML/PSO/RAGE et le streaming demandent aussi un formatage/enregistrement spécifique au moteur. Les tests hôtes de l'overlay ne prouvent pas le support de mods complets en jeu.
6. La version **PS4 1.32** est une cible séparée, pas un simple changement de variable.

## 9. Hygiène, vérité et attentes

- **Ne pas publier** : l'EBOOT, RPF, ASI/DLL d'origine, ressources propriétaires, données RAM, logs contenant des adresses d'appareils, IP privées/Tailscale, secrets, chemin Windows utilisateur, PRX/ELF propriétaires ou fichiers de sauvegarde.
- Le dépôt GitHub est **public**. Les petits snippets source et rapports *sans données de jeu* peuvent y être publiés après audit. L'EBOOT de l'utilisateur doit rester dans un espace privé.
- L'assistant précédent **n'a pas réussi à fabriquer un modloader en jeu**. Le projet produit un simulateur solide et des outils de validation. Le **dernier constat réel** est un **mismatch bloquant** entre profil EBOOT statique et signatures du processus chargé. La priorité est de comprendre ce mismatch **sans contester par défaut la provenance du fichier confirmée par l'utilisateur**.
- Si la nouvelle IA ne peut pas accéder au Windows du propriétaire, à la console ou au fichier EBOOT original, qu'elle indique précisément le manque et propose une procédure reproductible au lieu de prétendre qu'elle a réalisé des tests console.
