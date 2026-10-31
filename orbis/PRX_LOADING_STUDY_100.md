# Chargement du PRX dans RDR2 PS4 1.00 sur PS5 13.40 — étude (31 octobre 2026)

Configuration : Y2JB + Kstuff Lite + ShadowMountPlus, Payload Manager,
ps5debug-NG v1.3.2, **pas d'etaHEN**. Rien n'a été écrit dans le jeu pour
cette étude : uniquement CMD_PROC_MAPS et des CMD_PROC_READ bornés.

## Acquis vérifiés en lecture seule

- Image EBOOT : base `0x00400000`, quatre régions `executable` contiguës
  (r-x, r--, rw-, rw-). Adresse = base + RVA du profil. Profil fiPackfile8
  complet validé (`tools/ps5debug_ng_rdr2_100_live_profile.py`, exit 0).
- **Registre `fiCollection` validé** (`tools/ps5debug_ng_rdr2_100_registry_probe.py`,
  exit 0) : `base + 0x08053D40` est un tableau de pointeurs ; sur les 64
  premiers objets, 63 sont des `fiPackfile8` (vptr `base+0x066B00F8`, index
  u16 à `+8` égal au slot). Le slot 0 est un `rage::pgRawStreamer`
  (vtable RVA `0x066B2018`, identifiée par sa RTTI). Les 512 premiers slots
  sont non nuls. Le scanner C `runtime/rdr2_100_registry.c` filtre déjà ce cas.
- Modules du processus (noms de cartes VM) : modules du jeu
  `libSceFios2.prx` et `libc.prx` vers `0x80000000` ; modules système
  PS4 dont `libkernel.sprx` vers `0x800000000`, `libSceLibcInternal.sprx`,
  `libSceSysmodule.sprx`, etc. Ce sont des adresses de CE lancement.

## Primitives ps5debug-NG disponibles (formats vérifiés dans le source)

Pas de commande « charger un PRX ». Trames vérifiées (PROTOCOL.md + `proc.c`,
corps après l'en-tête 12 o `magic/cmd/datalen`, little-endian, `CMD_SUCCESS`
= `0x80000000`, `CMD_ERROR` = `0xF0000001`) :

- `CMD_PROC_ALLOC 0xBDAA000B` — req `{u32 pid; u32 length}` → `{u64 address}`.
- `CMD_PROC_FREE 0xBDAA000C` — req `{u32 pid; u64 address; u32 length}`.
- `CMD_PROC_WRITE 0xBDAA0003` — req `{u32 pid; u64 address; u32 length}`,
  puis `OK`, puis `length` octets bruts, puis `OK` final.
- `CMD_PROC_CALL 0xBDAA0006` — req 68 o `{u32 pid; u64 rpcstub; u64 rip;
  u64 rdi; u64 rsi; u64 rdx; u64 rcx; u64 r8; u64 r9}` → `{u32 pid; u64 rax}`.
- `CMD_PROC_ELF_RPC 0xBDAA0010` — req `{u32 pid; u32 length}` + ELF brut ;
  charge **et exécute** l'ELF (renvoie `entry`). Pas de `rpcstub` requis.

**Point dur, vérifié dans `proc.c`** : `CMD_PROC_INTALL` (0xBDAA0005) est un
**no-op** (`resp_rpcstub = 0`, aucune injection). `CMD_PROC_CALL` transmet
`rpcstub` tel quel au noyau (`sys_proc_cmd SYS_PROC_CALL`). Donc **savoir si
`CALL` fonctionne avec `rpcstub=0` dépend du plugin noyau** — invérifiable
hors console. Si `CALL` échoue en live, repli sur `CMD_PROC_ELF_RPC`.

L'instrument `tools/ps5debug_ng_rdr2_100_inject.py` implémente ALLOC/WRITE/
CALL avec ces formats, **dry-run par défaut**, barrière de profil, refus de
deviner l'adresse (`--loader-addr` obligatoire), `--arm` pour exécuter.

Méthode initialement envisagée — `CMD_PROC_CALL(sceKernelLoadStartModule,
chemin, …)` — **écartée** : voir la table d'imports ci-dessous, le jeu
n'importe pas ce symbole et son GOT est à zéro en RAM. Il faut d'abord
obtenir une adresse de primitive fiable (section « GOT lue à zéro »). Le PRX
actuel reste passif (aucun hook).

## Table d'imports de l'EBOOT (vérifiée hors-ligne)

`tools/inspect_rdr2_imports.py` (SHA-256 1.00, lecture seule, testé par
`tests/test_inspect_rdr2_imports.py` avec paires NID connues :
malloc=`gQX+4GDQjpM`, printf=`hcuQgD53UxM`,
sceKernelLoadStartModule=`wzvqT4UqKX8`). 665 imports JMPREL, 687 symboles,
`DT_SCE_PLTGOT` RVA `0x0678CC50`. Résultats clés :

| Symbole | Importé | GOT (r_offset) RVA |
| --- | --- | --- |
| `sceKernelLoadStartModule` | **non** | — |
| `sceKernelLoadStartModuleForPlugin` | non | — |
| `sceSysmoduleLoadModule` | **oui** | `0x0678CEB8` |
| `sceKernelOpen` | oui | `0x0678CDA0` |
| `sceKernelStat` | oui | `0x0678D128` |
| `stat` | oui | `0x0678DD40` |
| `fopen` | oui | `0x0678DD98` |
| `malloc` | oui | `0x0678D478` |
| `printf` | oui | `0x0678CFF0` |

Conséquence directe : la méthode « CALL sur une entrée GOT de
`sceKernelLoadStartModule` du jeu » est **impossible** — le jeu n'importe pas
ce symbole. `sceSysmoduleLoadModule` est importé mais ne charge que des
modules système par identifiant, pas un PRX arbitraire par chemin.

## Mécanisme d'import vérifié dans le FICHIER (PLT paresseux + RELRO)

Analyse directe de `eboot.bin` (sans console) via `inspect_rdr2_imports.py`
(champs `file_value`/`kind`). Programme headers réels :

- `PT_LOAD` r-x : off `0x4000`, va `0x0`, taille `0x06413B30`.
- `PT_SCE_RELRO` (`0x61000010`) r-- : off `0x6418000`, va `0x06414000`,
  fsz `0x37A130`, msz `0x37C000` → contient le GOT.
- `PT_LOAD` rw- : va `0x06790000`. `DT_SCE_PLTGOT` RVA `0x0678CC50`.

Chaque slot GOT d'import contient **dans le fichier** un pointeur vers
`PLT+6` (`kind = lazy-plt-stub`), pas zéro. Exemple
`sceSysmoduleLoadModule` : GOT `0x0678CEB8` → `0x05A73626`, stub PLT à
`0x05A73620` :

```
ff 25 92 98 d1 00   jmp qword [rip+0xd19892]  ; cible = 0x0678CEB8 (le slot)
68 4a 00 00 00      push 0x4a                  ; index de relocation
e9 40 fb ff ff      jmp PLT0
```

C'est une liaison paresseuse x86-64 standard. **Mais** le GOT est dans un
segment `PT_SCE_RELRO` (r--) : après relocation, le chargeur le passe en
lecture seule, ce qui **force une liaison immédiate (BIND_NOW)**. Donc à
l'exécution, `image_base + got_rva` doit contenir l'adresse résolue de la
fonction dans le module système.

## GOT lue à zéro en RAM : à re-vérifier (non bloquant)

Une seule lecture live antérieure avait renvoyé zéro à ces RVA. Le fichier
montre qu'elles ne sont **pas** zéro et que le GOT est bien l'emplacement de
liaison. Ce « zéro » est donc **suspect** (mauvaise adresse lue, page non
lue, ou état du jeu) et **non** une preuve que la voie est impossible —
à re-tester quand le jeu tourne, avec la recette exacte ci-dessous. La vtable
fiPackfile8 (`base + 0x066B00F8`, même segment RELRO) étant correctement lue,
le segment est lisible.

**Recette de re-test (lecture seule, jeu lancé) :** `sceKernelLoadStartModule`
vit dans `libkernel`. Comme le jeu importe `sceKernelOpen` (libkernel), lire
8 octets à `image_base + 0x0678CDA0`. Attendu : un pointeur dans la région
r-x de `libkernel` (pas `0x05A733F6`, la valeur fichier non liée). Croiser ce
pointeur avec `CMD_PROC_MAPS` pour obtenir la base de `libkernel`, puis
parcourir sa table d'exports (NID `wzvqT4UqKX8`) pour résoudre l'adresse de
`sceKernelLoadStartModule`. Cette adresse alimente `--loader-addr` de
l'instrument d'injection.

**Cette recette est outillée** : `tools/ps5debug_ng_rdr2_100_resolve_loader.py`
(lecture seule, `CMD_PROC_READ` + `CMD_PROC_MAPS` uniquement, barrière de
profil `check_live`, testé par `tests/test_ps5debug_ng_rdr2_100_resolve_loader.py`
avec un module libkernel synthétique). Il lit le slot GOT ancre, trouve le
module conteneur via maps, parse sa table d'exports Orbis en RAM (en-tête ELF
→ `PT_DYNAMIC`/`PT_SCE_DYNLIBDATA` → `SYMTAB`/`STRTAB`) et renvoie
`loader_addr` + un `inject_hint` (`--loader-addr 0x…`). Il **ne devine rien** :
si le slot ancre pointe encore dans l'image du jeu (`status`
`anchor-unresolved-in-image`) ou si le NID cible est absent du module ancre
(`target-not-exported-by-anchor-module`), il renvoie l'état sans adresse.
`loader_addr` est propre à CE lancement (ASLR) : à ré-exécuter avant chaque
session d'injection.

Voies de chargement (inchangées, à départager après le re-test) :
(a) résoudre depuis la base du module `libkernel.sprx` (vu en maps vers
`0x800000000`) via sa table d'exports ; (b) `CMD_PROC_ELF_RPC`
(`0xBDAA0010`) avec un stub autonome.

## Bloquants restants

1. **Adresse d'une primitive de chargement inconnue.** Confirmé ci-dessus :
   le GOT du jeu ne la fournit pas (zéro en RAM) et
   `sceKernelLoadStartModule` n'est pas importé. Aucune adresse ne doit être
   devinée. Voies recommandées : (a) ou (b) de la section précédente.
2. **Chemin visible depuis le bac à sable du jeu.** Un chemin `/data/...`
   n'est pas garanti visible par un processus PS4 sous Kstuff Lite. À tester
   par un appel en lecture (par exemple `stat`) avant tout chargement.
3. **Format du PRX.** OpenOrbis produit un SELF « fake-signed » ; son
   acceptation par le chargeur dépend de Kstuff Lite pour un processus PS4.
   Non testé.
4. **Premier acte d'écriture.** ALLOC/WRITE/CALL modifient l'état du jeu.
   À faire uniquement avec accord explicite du propriétaire, jeu en mode
   Histoire hors ligne, sauvegarde faite, en acceptant un possible plantage
   du jeu (sans effet sur la console ou les sauvegardes existantes).

## Feuille de route honnête vers un mod VISIBLE en jeu

Un mod qu'on voit dans RDR2 est le sommet du projet ; il reste plusieurs
maillons **non prouvés**, dont chacun exige le jeu lancé :

1. **Résoudre `--loader-addr`** (recette ci-dessus, lecture seule). —
   **outillé** (`tools/ps5debug_ng_rdr2_100_resolve_loader.py`), à exécuter en
   live pour obtenir l'adresse réelle (encore non lancé sur console).
2. **Faire tourner notre code** : `inject.py --arm` (CALL), ou repli
   `CMD_PROC_ELF_RPC`. Preuve réelle = trace `[LML-RAGE-VFS] MODULE_ENTRY` et
   un handle renvoyé. — non testé sur console.
3. **Accepter le fake-SELF** sous Kstuff Lite pour un process PS4. — non testé.
4. **Installer le détour `fiPackfile8`** 1.00 : le module actuel
   (`runtime/rage_vfs_redirect`) a tout le corps read-through mais
   `lml_rage_game_hook_installed()` renvoie 0 — **le détour n'existe pas**.
   Slots vtable 1.00 connus (Open `0x0452A480`, Read `0x0452B9D0`, etc.).
   — à écrire et vérifier.
5. **Fichier moddé** produisant un effet visible (remplacement d'une ressource
   RAGE via `overlay.map`). — à préparer.

Aucun de ces maillons ne peut être validé tant que le jeu ne tourne pas. Le
premier résultat réel atteignable est l'étape 2 (notre module qui s'exécute),
pas encore un changement visible.

## Ce qui n'est PAS fait

Aucun ALLOC, WRITE, CALL, ELF ou attach **exécuté**. Aucun PRX chargé. Aucun
détour installé. L'instrument d'injection existe mais n'a jamais été armé.
