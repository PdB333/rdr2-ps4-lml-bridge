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

Méthode envisagée : allouer une petite zone, y écrire le chemin du PRX,
puis `CMD_PROC_CALL(sceKernelLoadStartModule, chemin, 0, 0, 0, 0, 0)` ;
le handle renvoyé (> 0) et le journal `[LML-100-TRACE] MODULE_ENTRY`
prouveraient le chargement. Le PRX actuel est passif (aucun hook).

## Bloquants restants

1. **Adresse de `sceKernelLoadStartModule` inconnue.** La table des symboles
   de `libkernel.sprx` n'est pas mappée côté utilisateur ; aucune adresse ne
   doit être devinée. Voie recommandée : à partir de l'EBOOT privé, lire la
   table d'imports (DT_SCE_*, relocations `JUMP_SLOT`) pour trouver l'entrée
   GOT de ce symbole, si le jeu l'importe ; puis **lire** cette entrée en RAM
   (base + RVA du GOT) et exiger qu'elle pointe dans la région r-x de
   `libkernel.sprx`. Si RDR2 ne l'importe pas, il faudra une autre
   source fiable (par exemple via `libSceSysmodule`), à étudier.
   **Nécessite l'EBOOT** : il n'est pas sur ce PC.
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
