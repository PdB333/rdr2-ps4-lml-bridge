# Plugin TacHen « preuve de vie » — LML Bridge (RDR2 PS4 1.00)

But du spike : **prouver que notre code s'exécute dans le process de RDR2 1.00**
via le chargeur de plugins **TacHen**, sans toucher à la mémoire du jeu. C'est
la voie retenue après l'abandon de `resolve_loader`/`ELF_RPC` (l'en-tête ELF
n'est pas mappée en RAM sur Orbis — cf. `orbis/PRX_LOADING_STUDY_100.md`).

## Ce que fait le plugin

[`lml_plugin.c`](lml_plugin.c) exporte la convention de module SCE PRX :

- `module_start(argc, argv)` : appelé par TacHen sur un pthread du jeu. Écrit
  une ligne horodatée dans `/data/lml_bridge_spike.log` puis renvoie `0`
  (succès → TacHen garde le module résident). **Ne touche pas** la mémoire de
  RDR2.
- `module_stop(argc, argv)` : log de déchargement.

Le point `HOOK` marqué dans la source est l'endroit où, **une fois les
signatures fiPackfile8 validées en live**, on appellera
`runtime/rdr2_100_packfile_hooks.c` pour armer le détour. Interdit tant que ce
n'est pas validé.

## Chaîne de build (vérifiée le 2 nov. 2026)

Le build réel tient en **4 étapes** (voir [`build.cmd`](build.cmd), c'est le
chemin canonique sous Windows). Les wrappers `prospero-clang`/`prospero-lld`
**ne conviennent pas** ici : les `bin/*` sont des scripts Linux, et
`win/prospero-lld.exe` ajoute `-pie` en dur, incompatible avec `--shared`. On
appelle donc `clang` puis `ld.lld` directement avec les flags SCE du driver.

1. **compile** : `clang -target x86_64-sie-ps5 -c` → `lml_plugin.o`.
2. **link partagé** : `ld.lld -m elf_x86_64_fbsd … --default-script
   target/lib/prx.script --shared` → `lml_plugin.prx`. Les imports
   `open`/`write`/`close`/`clock_gettime` restent des stubs résolus par le
   chargeur TacHen contre `libSceLibcInternal` (pas `payload_args`/`dlsym`).
3. **patch e_type** : `ld.lld --shared` émet `ET_DYN` (3) ; `make_fself` et le
   validateur TacHen n'acceptent que les types SCE. [`patch_etype.py`](patch_etype.py)
   force `e_type = 0xfe18` (`ET_SCE_DYNAMIC`).
4. **fake-sign** : `make_fself.py --ptype fake` → `lml_plugin.sprx` (SELF
   fake-signé, magic dev `0x1d3d154f`).

```bat
plugin\tachen\build.cmd
```

### Toolchain portable (sans installeur)

Tout en extract-and-go sous `C:/Users/Selat/ps5-tools/` :

- **LLVM 23.1.4** (`clang+llvm-23.1.4-x86_64-pc-windows-msvc`, archive portable
  officielle) — fournit `clang.exe` **et** `ld.lld.exe`, qui connaissent la
  cible `x86_64-sie-ps5` (support PS5 en amont depuis LLVM 16).
  > Zig 0.14.1 (build de TacHen) ne convient PAS ici : son parseur de triple
  > rejette `x86_64-sie-ps5` (`UnknownOperatingSystem`). Zig sert à TacHen pour
  > un payload `x86_64-linux-none`, pas pour un PRX SCE.
- **PS5 Payload SDK v0.43** (`ps5-payload-sdk.zip`, release prebuilt) — fournit
  le sysroot `target/` (stubs `libSceLibcInternal`/`libkernel_web`…, `prx.script`)
  et `make_fself.py`. La copie source « ps5-payload sdk » n'a PAS de `target/`
  → inutilisable seule.

`build.cmd` prend `PS5_PAYLOAD_SDK` et `LLVMBIN` depuis l'environnement, avec
ces chemins par défaut.

### Contraintes du validateur TacHen (confirmées, `platform/native/prx-image.c`)

Le `.sprx` doit passer `tac_prx_inspect` :

- SELF magic `0x1d3d154f` (plateforme non spécifiée → **prend la plateforme du
  jeu enregistré**, donc PS4 pour RDR2 1.00) ou `0xeef51454` (force PS5). Pour
  un jeu PS4, `make_fself --ptype fake` (→ `0x1d3d154f`) convient.
- ELF embarqué : `ET_SCE_DYNAMIC` (**`0xfe18`**), machine 62, version 1,
  ehsize 64, phentsize 56. La cible `x86_64-sie-ps5` émet ce type ; `make_fself`
  **rejette** un ELF `ET_DYN` ordinaire (il n'accepte que les types SCE/EXEC).
- Doit contenir `PT_DYNAMIC`/`PT_SCE_DYNLIBDATA` **et** un `PT_LOAD` exécutable.

**Vérification sous `tac_prx_inspect` réel** : [`validate_against_tachen.c`](validate_against_tachen.c)
compile `prx-image.c` de TacHen tel quel et contrôle le `.sprx` avant tout essai
console. Résultat obtenu sur `lml_plugin.sprx` (18720 o) :

```
taille=18720 rc=0 platform=0 (non specifie -> plateforme du jeu)
ACCEPTE par tac_prx_inspect
```

> **Portée : validation de conteneur uniquement.** `rc=0` prouve que le `.sprx`
> satisfait le contrôle d'en-tête/d'import de TacHen. Cela ne prouve PAS que
> `module_start` s'exécute en jeu, ni que les imports se résolvent live, ni
> aucun comportement console. Le jalon « notre code tourne dans RDR2 1.00 »
> reste à établir par un chargement manuel réel (ligne écrite dans
> `/data/lml_bridge_spike.log`).

## Enregistrement côté TacHen

À confirmer contre le dépôt TacHen avant tout essai console (la spec plugin
vient de `docs/PRX-CONTAINER-COMPATIBILITY.md` de TacHen, non clonée ici) :

- Déposer le `.sprx` dans
  `/data/tachen/module-files/v1-p<platform>-<hostSDK>/` (monté r-x sur
  `/tachen-modules`).
- Enregistrer le plugin pour **RDR2 version 1.00 exacte** (Title ID CUSA08519).
- Chargement **manuel** en jeu (pas d'autostart).

## Preuve de vie attendue

Après chargement manuel depuis TacHen, `module_start` écrit dans
`/data/lml_bridge_spike.log` :

```
[LML] <timestamp> module_start: notre code tourne dans le process RDR2 1.00
```

La présence de cette ligne = **notre code s'exécute dans le jeu**. C'est le
jalon que valide ce spike. Rien n'est écrit dans la mémoire du jeu.

## Points à verrouiller avant la console

- [x] Toolchain portable installé, build reproductible (`build.cmd`).
- [x] `.sprx` accepté par le vrai `tac_prx_inspect` de TacHen.
- [ ] Chargement manuel réel + ligne dans `/data/lml_bridge_spike.log`
  (= preuve d'exécution en jeu ; non encore établie).
- [ ] Ensuite seulement : greffer l'armement `rdr2_100_packfile_hooks` dans
  `module_start`, après validation live des signatures fiPackfile8.
