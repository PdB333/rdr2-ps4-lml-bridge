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

## Primitives ps5debug-NG disponibles (PROTOCOL.md amont)

Pas de commande « charger un PRX ». Primitives utiles :
`CMD_PROC_ALLOC 0xBDAA000B`, `CMD_PROC_WRITE 0xBDAA0003`,
`CMD_PROC_CALL 0xBDAA0006` (rip + 6 arguments, renvoie rax),
`CMD_PROC_ELF_RPC 0xBDAA0010`, `CMD_PROC_PROTECT 0xBDAA0008`.
`CMD_PROC_INTALL` est un stub (renvoie 0).

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

## GOT lue à zéro en RAM (constat ouvert)

Lecture seule des RVA GOT ci-dessus en RAM (`base + 0x0678Cxxx`,
région RELRO r-- `0x06814000`–`0x06B90000`) : **toutes à zéro**, alors que la
vtable fiPackfile8 (`base + 0x066B00F8`, même région) est correctement
peuplée. Donc les pointeurs de fonctions importées **ne sont pas lisibles
dans un GOT data** à ces adresses. Deux explications candidates, non
tranchées (aucune écriture faite) :

1. le chargeur Orbis sous ce jailbreak patche directement les stubs PLT
   (région r-x) plutôt que de remplir un GOT data ;
2. ces slots relèvent d'une liaison paresseuse non encore déclenchée.

Conséquence : l'adresse d'une fonction `libkernel`/`libc` pour un
`CMD_PROC_CALL` **ne peut pas** être moissonnée depuis le GOT du jeu. Voies à
étudier : (a) résoudre depuis la base du module `libkernel.sprx` mappé dans le
processus (vu en maps vers `0x800000000`) via sa propre table d'exports, si
ps5debug-NG expose l'info module ; (b) utiliser `CMD_PROC_ELF_RPC`
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

## Ce qui n'est PAS fait

Aucun ALLOC, WRITE, CALL, ELF ou attach. Aucun PRX chargé. Aucun hook.
