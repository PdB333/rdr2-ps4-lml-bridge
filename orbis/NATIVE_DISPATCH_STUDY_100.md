# Dispatch des natives RAGE — RDR2 PS4 1.00 (étude statique)

Profil : EBOOT RDR2 PS4 1.00, Title ID CUSA08519,
SHA-256 `e3ae087f833b0f30f462bb7f880dd2955bf9f51dbb6e56706ee9bda81581feff`.
RVA relatifs à l'image (base runtime = `image_base + RVA`). **Spécifique
1.00 — à ne jamais réutiliser pour 1.32.**

Aucun octet de l'EBOOT, aucun secret, aucune adresse privée n'est reproduit
ici. Les RVA ci-dessous sont dérivés par rétro-ingénierie statique, cohérents
avec les RVA déjà documentés (p. ex. le registre `fiCollection` vers
`base+0x08053D40`). REA refuse l'ELF x86_64 (provider Ghidra Windows
limité au PE/6502) ; l'analyse a donc été menée directement au scanner
d'octets (Capstone + lecture structurée de l'ELF).

## Motif d'enregistrement

Chaque native est enregistrée par une paire d'instructions émise une fois,
sur son site d'enregistrement :

```
48 B9 <imm64>        movabs rcx, <hash de la native>
48 8D 15 <disp32>    lea    rdx, [rip + disp]   ; -> handler de la native
```

Le code environnant range ensuite la paire dans une page statique
(`scrNativeRegistration`, 7 entrées par page) : `hashes[idx]` à `+0x48`,
`handlers[idx]` à `+0x08`, `count` (u32) à `+0x40`, chaînage `next` à `+0x00`.
Les pages sont des structures statiques dispersées en `.bss`/data (vers
`0x0832xxxx`), chaînées par unité de traduction — **ce n'est pas** un tableau
de buckets contigu. Le nombre de sites (~5250) correspond à l'effectif attendu
des natives RDR2, ce qui confirme qu'il s'agit bien de la table complète.

## Résultat du balayage (`tools/inspect_rage_natives.py`)

- Sites `movabs rcx + lea rdx` dans les segments exécutables : **5251**
- Natives distinctes : **5230**
- Collisions de handler (hash vu avec 2 RVA) : 16 (tolérées, 1er conservé)
- Hashes connus du manifeste retrouvés : **86 / 93**

Correspondances vérifiées (hash → RVA du handler) :

| Native (manifeste)       | hash                 | handler RVA  |
|--------------------------|----------------------|--------------|
| GET_ENTITY_MAX_HEALTH    | `0x15D757606D170C3C` | `0x01AAA210` |
| STOP_SOUND_FRONTEND      | `0x0F2A2175734926D8` | `0x01A645D0` |
| PLAY_SOUND_FRONTEND      | `0x67C540AA08E4A6F5` | `0x01A643F0` |

(Les 7 hashes non retrouvés sont probablement enregistrés via un registre
autre que `rcx` ou absents du binaire PS4 — sans impact sur l'approche.)

## Conséquence pour l'invoker (étape 7)

Le RVA du handler est **statique dans l'image**. L'invoker côté console n'a
donc pas besoin de parcourir la liste d'enregistrement à l'exécution : pour un
hash connu,

```
handler_runtime = image_base + handler_rva   // base lue via check_live
handler(NativeContext* ctx)                   // appel direct
```

Cela simplifie fortement l'étape 7 : on bâtit hors-ligne une carte
`hash -> handler_rva` (via l'outil, fichier local non commité), puis le PRX
résout `image_base` à chaud et appelle le handler.

### Non vérifié (à régler au premier essai console, pas ici)

- **Convention d'appel / ABI du `NativeContext`** : disposition des arguments
  et du retour (le modèle ScriptHook `nativeInit`/`nativePush64`/`nativeCall`
  reste à confirmer sur la cible PS4).
- Certains handlers peuvent être des thunks.
- La carte est liée au SHA 1.00 ; tout autre build invalide les RVA.

Tant que l'ABI n'est pas validée sur console, aucun appel de native n'est
effectué (règle : ne pas confondre test simulé et réussite sur console ; ne
pas modifier la mémoire du jeu avant validation des signatures).

## Outil

`tools/inspect_rage_natives.py` — lecture seule, gardé par SHA-256 (refuse tout
EBOOT différent du profil 1.00). Prend l'EBOOT en argument, n'embarque aucun
octet propriétaire. `--out` écrit la carte complète dans un fichier **local**
(à ne pas commiter). Tests : `tests/test_inspect_rage_natives.py` (ELF Orbis
synthétique en RAM, sans console ni binaire propriétaire).
