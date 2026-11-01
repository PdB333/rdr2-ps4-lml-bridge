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

## Ce qui reste (console)

- **Charger un PRX** fournissant les deux trampolines (handlers Open/Read qui
  lisent à travers vers l'original puis consultent l'`OverlayIndex`). Sans lui,
  `--arm` est impossible par conception — rien à armer.
- Prouver l'effet visible réel avec une ressource `.meta` 1.00 réelle
  (cf. [OVERLAY_VISIBLE_EFFECT_100](OVERLAY_VISIBLE_EFFECT_100.md)).
- L'ABI du `NativeContext` reste non validée
  (cf. [NATIVE_DISPATCH_STUDY_100](NATIVE_DISPATCH_STUDY_100.md)).
