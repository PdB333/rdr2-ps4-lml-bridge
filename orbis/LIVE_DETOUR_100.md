# Outil d'application live du détour fiPackfile8 — RDR2 PS4 1.00

`tools/ps5debug_ng_rdr2_100_detour.py` : pendant live du planner hors-ligne
`runtime/rdr2_100_detour.{h,c}`. Il pilote le **même** swap de pointeurs de
vtable sur le jeu en cours via ps5debug-NG, sous le même contrat fail-closed.

Profil cible : EBOOT 1.00, CUSA08519, SHA-256
`e3ae087f833b0f30f462bb7f880dd2955bf9f51dbb6e56706ee9bda81581feff`,
PS5 FW 13.40, sans etaHEN.

## Validation live (lecture seule) — 1 nov. 2026

Signatures `fiPackfile8` confirmées sur la console réelle via
`ps5debug_ng_rdr2_100_live_profile.py` (uniquement `CMD_PROC_READ`) :

```
FW 13.40 · CUSA08519 · metadata 01.00 · PID 176 · image_base 0x400000
régions: r-x 0x400000–0x6814000 · r-- RELRO 0x6814000–0x6B90000 · rw- …
RTTI, header vtable, boundary, 5 slots connus, 112 méthodes (fnv64
8eaecb696678dad0), 4 préfixes de code : TOUS conformes à l'EBOOT 1.00.
```

La contrainte « ne pas modifier la mémoire avant validation des signatures »
est donc **levée pour la zone `fiPackfile8`** (site du détour vérifié, non
deviné). Réserve : le SHA-256 complet de l'exécutable en mémoire n'est pas
prouvé — seules les 112 adresses normalisées le sont.

## Ce que fait l'outil

- **Dry-run par défaut.** Aucun octet écrit sans `--arm` (installe) ou
  `--revert` (restaure).
- Gate sur `check_live` : refuse si le profil `fiPackfile8` ne correspond pas,
  ou si les slots 2/13 ne sont pas confirmés live.
- Calcule les 2 cibles depuis la base live : slot Open `base+0x66B0108`
  (original `base+0x452A480`), slot Read `base+0x66B0160` (original
  `base+0x452B9D0`). Dry-run live observé : `0x6AB0108` / `0x6AB0160`.
- **Aucune adresse devinée.** `--arm` exige `--trampoline-open` ET
  `--trampoline-read` (adresses runtime d'un module déjà chargé) ; l'outil ne
  fabrique pas de trampoline.
- Refuse d'écrire ailleurs que dans la région RELRO (jamais dans le r-x `.text`).
- Écritures via le `CMD_PROC_WRITE` vérifié (même layout que l'outil d'injection),
  2 pointeurs de 8 octets.

Commandes :

```bash
# Dry-run (lecture seule, jeu lancé)
python -B ps5debug_ng_rdr2_100_detour.py --ip <ps5> --tailscale
# Installer (une fois un PRX chargé fournissant les 2 trampolines)
python -B ps5debug_ng_rdr2_100_detour.py --ip <ps5> --tailscale --arm \
    --trampoline-open 0x<addr> --trampoline-read 0x<addr>
# Restaurer
python -B ps5debug_ng_rdr2_100_detour.py --ip <ps5> --tailscale --revert
```

Tests à sec (sans console) : `tests/test_ps5debug_ng_rdr2_100_detour.py`
(rapport synthétique + faux socket capturant les écritures ; math des slots,
refus profil/slots/trampolines/`.text`, dry-run, arm, revert).

## RELRO

La vtable est en RELRO (r--). `CMD_PROC_WRITE` de ps5debug-NG passe par la
primitive d'écriture noyau, qui patche les pages indépendamment de la
protection utilisateur (c'est ainsi que ps4debug/ps5debug patchent le code en
lecture seule). Si une console future rejette l'écriture, une étape de
changement de protection **vérifiée** devra être ajoutée — aucun opcode de
protection n'est deviné dans ce dépôt aujourd'hui.

## ABI des handlers Open/Read (hypothèse statique)

Avant d'écrire un trampoline il faut connaître la convention d'appel exacte des
deux méthodes — la deviner planterait le jeu. `tools/inspect_rage_packfile_abi.py`
désassemble statiquement les deux handlers depuis l'EBOOT (read-only, gaté SHA,
listing complet en fichier local non commité) et infère les registres
d'arguments lus avant d'être écrits :

| Handler            | RVA          | Args entrants             | Prologue        |
|--------------------|--------------|---------------------------|-----------------|
| `Open` (slot 2)    | `0x0452A480` | `rdi, rsi, rdx` (3)       | `push rbp`, 24o |
| `Read` (slot 13)   | `0x0452B9D0` | `rdi, rsi, rdx, rcx, r8` (5) | `push rbp`   |

Lecture SysV : `Open(this, const char* path, int64 read_only)` et
`Read(this, handle, buffer, size, +1)`. **Hypothèse STATIQUE** — à confirmer
live avant d'armer. Test : `tests/test_inspect_rage_packfile_abi.py` (ELF
synthétique, stubs encodés à la main ; aucun octet du jeu).

### Cycle de vie close/seek/size — identifié statiquement (Ghidra), NON validé live

L'heuristique `--sweep` par compte d'arguments ne suffisait pas (beaucoup de
handlers lisent un champ de `this` avant de toucher le handle → contiguïté
sous-compte). Les slots ont depuis été désignés par **décompilation sémantique
Ghidra headless** de la vtable `fiPackfile8` (RVA `0x066B00F8`, base Ghidra 0 ;
critère = retour de l'expression de taille canonique et forme `(this, handle)`,
pas un simple compte d'arguments) :

| Opération            | Slot  | Offset vtable | RVA (base 0)            | Confiance            |
|----------------------|-------|---------------|-------------------------|----------------------|
| Close                | 19    | `+0x98`       | `0x0452BE00`            | solide (double-confirmé) |
| Seek32 / Seek64      | 17/18 | `+0x88`/`+0x90` | `0x0452BA90`/`0x0452BAA0` | solide            |
| Size32 / Size64      | 22/23 | `+0xB0`/`+0xB8` | `0x0452BE30`/`0x0452BE80` | solide            |
| Read (primitive)     | 11    | `+0x58`       | `0x0452A870`            | solide — voir note   |
| Read (forwarder)     | 13    | `+0x68`       | `0x0452B9D0`            | solide               |

- **Close = slot 19** : `func_0x04524610(handle); return 0;` — libère le handle ;
  réutilisé comme primitive close par slot 12.
- **Seek = slots 17/18** : bornage offset vs taille, param `whence` ; paire 32/64.
- **Size = slots 22/23** : signature `(this, handle)`, retournent
  `(entry[0x14] & 0xfffffff0) + (entry[2] & 0xfffffff0)` (entrée compressée),
  chemin « taille brute » `return entry[2]` sinon ; paire 32/64 comme Seek.
- **Read** : slot 11 est la primitive interne du moteur (wrappée par slot 48
  ReadFull) ; slot 13 forwarde vers un objet-membre (`*(this+0x10)` vtable `+0x68`),
  une couche différente. Le hook actuel vise slot 13 — **à trancher live** par
  quelle couche passe le chargement d'assets story-mode 1.00 avant d'armer.

Helper résolveur handle→index partagé : `func_0x0452E970(this, handle, 0)`, puis
verrou `*this+0x1e0`, puis entrée table `this[0xf] + idx*0x18 (+0x110/0x118)`.

> **Identification statique ≠ validation console.** `lifecycle_verified` reste à
> **0** : les slots close/seek/size sont désignés mais ni hookés ni vérifiés sur
> console, et le point d'interception Read (slot 11 vs 13) n'est pas tranché.
> Ne pas armer tant que ces slots ne sont pas hookés **et** validés live. Le
> détour actuel ne remet donc aucun bridge token au jeu.

> Conséquence : la voie packfile « handle » ne peut pas encore produire d'effet
> visible tant que ce cycle de vie n'est pas validé live. La voie **text-loader**
> (`lml_rage_dispatch_text_loader`, un seul appel synchrone, sans handle
> persistant) reste l'option offline-safe qui n'a besoin ni de close/seek/size
> ni de leur validation.

## Hook bodies Open/Read (core clean-room)

`runtime/rdr2_100_packfile_hooks.{h,c}` : le **corps** des deux hooks, appelé
par le trampoline une fois les slots échangés. Il relie l'ABI statique récupérée
au backend read-through `lml_rage_*` (rage_vfs_redirect.h) :

- `lml_packfile_hook_open(self, path, read_only)` : consulte l'overlay ; si le
  chemin est remplacé (source OVERLAY, lecture seule), renvoie un **bridge
  token** et le mémorise ; sinon laisse le jeu ouvrir son propre handle natif.
- `lml_packfile_hook_read(self, handle, buffer, size, extra)` : sert les octets
  de l'overlay pour un bridge token, sinon transmet au `Read` original intact.
- `lml_packfile_hook_close(handle)` : libère le bridge token (slot close 19).
- `lml_packfile_hook_seek(handle, offset, whence, &out)` / `lml_packfile_hook_size(handle, &out)` :
  servent le flux overlay pour un bridge token (slots seek 17/18, size 22/23),
  et renvoient `NOT_BRIDGE` pour un vrai handle (le trampoline forwarde vers
  l'original) — même motif que close. Le `whence` du moteur est supposé POSIX et
  **doit être validé live** avant `lifecycle_verified = 1`.

Règles (comme `rdr2_100_natives`) : **pur/injectable** (l'original n'est atteint
que via des pointeurs fournis par l'appelant — jamais d'adresse jeu en dur),
**fail-closed**. Deux gates :

- `abi_verified` : l'ABI Open/Read est confirmée live. À 0 → pass-through total.
- `lifecycle_verified` : close/seek/size sont aussi hookés **et** vérifiés. À 0,
  **aucun** bridge token n'est remis au jeu (sinon un close/seek natif
  non-hooké sur un token planterait le moteur, cf. invariant de
  rage_vfs_redirect.h). Le chemin testé par défaut (Open/Read vérifiés,
  lifecycle non) est donc un pass-through sûr : fonctionnement original préservé.

Les slots close/seek/size sont désormais **désignés statiquement** (voir table
ci-dessus : close=19, seek=17/18, size=22/23) **et leurs hook bodies sont écrits
et testés hors ligne** (close/seek/size, harness `rdr2_100_packfile_hooks_harness.c`,
171 tests). Il reste à **valider live** leur ABI (dont le `whence` du moteur) et à
**trancher Read slot 11 vs 13** avant de passer `lifecycle_verified = 1`. Test :
`tests/test_rdr2_100_packfile_hooks.py` (harness C liant le backend réel, sert
`MODDED_CONTENT` vs `ORIGINAL_CONTENT` ; aucun octet du jeu).

## Publication des trampolines vers `--arm`

Le détour n'écrit jamais d'adresse devinée : `--arm` exige `--trampoline-open`
et `--trampoline-read`, les adresses **runtime** des deux thunks asm. La chaîne
prévue (console-only, **NON VÉRIFIÉE**) :

1. Un PRX chargé en mémoire expose deux thunks asm minces. Chaque thunk
   préserve la convention SysV, appelle le hook body C correspondant avec les
   arguments reçus (Open : `self, path, read_only` ; Read :
   `self, handle, buffer, size, extra`), et détient le pointeur « original »
   sauvegardé (la valeur de slot d'avant l'échange) pour le pass-through.
2. `module_start` du PRX publie les adresses runtime des deux thunks (p. ex.
   via un petit fichier JSON dans `/data/lml_bridge/` ou une lecture mémoire
   ciblée), que l'opérateur relit pour les passer à `--trampoline-open/-read`.
3. L'ordre d'échange des slots importe : publier/armer `Read` **avant** `Open`,
   pour qu'aucun bridge token ne puisse être lu par le `Read` original.

Tant que ce PRX + ses thunks ne sont pas écrits **et** que close/seek/size ne
sont pas hookés/vérifiés, `--arm` reste interdit par conception.

## Ce qui reste (console)

- **Écrire le PRX + les thunks asm** publiant les deux trampolines runtime.
- **Trancher Read slot 11 vs 13** (couche réelle du chargement story-mode) puis
  **hooker + vérifier live close=19 / seek=17,18 / size=22,23** (slots désignés
  statiquement, voir table) pour hooker le cycle de vie complet avant de remettre
  un bridge token au jeu. Sans cela, `--arm` reste impossible par conception.
- Prouver l'effet visible réel avec une ressource `.meta` 1.00 réelle
  (cf. [OVERLAY_VISIBLE_EFFECT_100](OVERLAY_VISIBLE_EFFECT_100.md)).
- L'ABI du `NativeContext` reste non validée
  (cf. [NATIVE_DISPATCH_STUDY_100](NATIVE_DISPATCH_STUDY_100.md)).
