# Plugin TacHen « preuve de vie » — LML Bridge (RDR2 PS4 1.00)

But du spike : **prouver que notre code s'exécute dans le process de RDR2 1.00**
via le chargeur de plugins **TacHen**, sans toucher à la mémoire du jeu. C'est
la voie retenue après l'abandon de `resolve_loader`/`ELF_RPC` (l'en-tête ELF
n'est pas mappée en RAM sur Orbis — cf. `orbis/PRX_LOADING_STUDY_100.md`).

## Ce que fait le plugin

[`lml_plugin.c`](lml_plugin.c) ne définit **pas** lui-même `module_start` : le
CRT OpenOrbis (`crtlib.o`) le fournit, ainsi que `module_stop`, `_init`,
`_fini`, la section `.data.sce_module_param` et le parcours de `.init_array`.
Notre code tient dans un **constructeur** (`__attribute__((constructor))`) que
le `module_start` du CRT appelle via `.init_array` :

- `lml_proof_of_life()` : écrit une ligne horodatée dans
  `/data/lml_bridge_spike.log` et sur la sortie debug (`sceKernelDebugOutText`).
  **Ne touche pas** la mémoire de RDR2.

Le point `HOOK` marqué dans la source est l'endroit où, **une fois les
signatures fiPackfile8 validées en live**, on appellera
`runtime/rdr2_100_packfile_hooks.c` pour armer le détour. Interdit tant que ce
n'est pas validé.

## Pourquoi un PRX PS4 (OpenOrbis), pas PS5

RDR2 est un **titre PS4**. Un premier essai en module PS5 (`-target
x86_64-sie-ps5` + `make_fself`) passait le contrôle de conteneur de TacHen mais
était **rejeté par le loader kernel** : `runtime.log` montrait
`Game module loader rejected file: 0x80020016` (`SCE_KERNEL_ERROR_EINVAL`),
`module_start` jamais exécuté. Le format attendu dans un process PS4 est un
**PRX PS4 OpenBorbis** (`--target=x86_64-pc-freebsd12-elf` + `create-fself`).
Les anciens fichiers de la voie PS5 ([`build.cmd`](build.cmd),
[`patch_etype.py`](patch_etype.py)) sont conservés comme trace de l'impasse.

## Chaîne de build PS4 (vérifiée le 2 nov. 2026)

[`build_ps4.ps1`](build_ps4.ps1), alignée sur `orbis/build_loader_smoke.ps1` :

1. **compile** : `clang --target=x86_64-pc-freebsd12-elf -fPIC` (libkernel
   seul, voir plus bas) → `lml_plugin_ps4.o`.
2. **link** : `ld.lld -pie --script link.x -e _init` avec **`crtlib.o`** et
   **`-lkernel` uniquement** → `lml_plugin_ps4.elf` (`ET_SCE_DYNAMIC` 0xfe18).
3. **fake-sign** : `create-fself --lib` → `lml_plugin_ps4.prx` (SELF magic dev
   `0x1d3d154f`). `create-fself` publie `module_start`/`module_stop` du CRT
   dans la table d'export SCE du module.

```powershell
powershell -ExecutionPolicy Bypass -File plugin\tachen\build_ps4.ps1
```

### Piège create-fself : duplicata de PT_LOAD (corrigé)

`create-fself` **dédouble le PT_LOAD inscriptible** (deux segments identiques et
superposés) quand ce segment est fabriqué « à la main » — c'était le cas avec un
`.data.sce_module_param` et un `module_start` écrits dans notre source. Ce
duplicata chevauchant fait échouer le contrôle d'overlap de `tac_prx_inspect`
(`platform/native/prx-image.c`, lignes 47-50) : rejet `Invalid native module
ELF headers`. En laissant **`crtlib.o`** fournir tout le scaffolding (comme
`loader_smoke`, seul PRX OpenOrbis sans duplicata) et en n'éditant **que
`-lkernel`** (la libc rajoute du `.bss` qui relance le dédoublement), la
disposition redevient **un seul** PT_LOAD inscriptible. [`inspect_prx.py`](inspect_prx.py)
dump les program headers du `.prx` et refait le contrôle d'overlap de TacHen.

### Contraintes du validateur TacHen (`platform/native/prx-image.c`)

- SELF magic `0x1d3d154f` (plateforme non spécifiée → **prend la plateforme du
  jeu enregistré**, donc PS4 pour RDR2 1.00).
- ELF embarqué : `ET_SCE_DYNAMIC` (**`0xfe18`**), machine 62, version 1,
  ehsize 64, phentsize 56 ; `PT_DYNAMIC`/`PT_SCE_DYNLIBDATA` **et** un `PT_LOAD`
  exécutable ; **aucun PT_LOAD chevauchant**.

**Vérification sous `tac_prx_inspect` réel** : [`validate_against_tachen.c`](validate_against_tachen.c)
compile `prx-image.c` de TacHen tel quel. Résultat sur `lml_plugin_ps4.prx`
(52736 o) :

```
taille=52736 rc=0 platform=0 (non specifie -> plateforme du jeu)
ACCEPTE par tac_prx_inspect
```

> **Portée : validation de conteneur uniquement.** `rc=0` prouve que le `.prx`
> satisfait le contrôle d'en-tête/d'import de TacHen — exactement ce que le
> build PS5 passait AUSSI avant d'être rejeté par le kernel. Cela ne prouve PAS
> que `module_start` s'exécute en jeu. Le seul juge est le `runtime.log` de
> TacHen lors d'un chargement manuel réel.

## Preuve de vie attendue

Après chargement manuel depuis TacHen, le constructeur écrit dans
`/data/lml_bridge_spike.log` :

```
[LML] <processtime> module_start: notre code tourne dans le process RDR2 1.00
```

La présence de cette ligne (ou de la même sur la sortie debug) = **notre code
s'exécute dans le jeu**. C'est le jalon que valide ce spike. Rien n'est écrit
dans la mémoire du jeu.

## Points à verrouiller avant la console

- [x] Recette PS4 reproductible (`build_ps4.ps1`), PRX accepté par le vrai
  `tac_prx_inspect`, **sans duplicata de PT_LOAD**.
- [ ] Chargement manuel réel + `runtime.log` montrant `module.start` sans rejet
  `0x80020016` (= preuve d'exécution en jeu ; non encore établie).
- [ ] Ensuite seulement : greffer l'armement `rdr2_100_packfile_hooks` dans le
  constructeur, après validation live des signatures fiPackfile8.
