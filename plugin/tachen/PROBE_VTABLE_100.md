# Validation live de la vtable fiPackfile8 (RDR2 PS4 1.00) — plugin lecture seule

Étape **avant tout détour** : prouver en live que les signatures statiques
(REA/Ghidra) correspondent à la mémoire réelle du jeu, **sans écrire un octet**
dans RDR2. Règle propriétaire : ne jamais patcher une adresse devinée, ne jamais
confondre test simulé et succès console.

## Ce que fait le plugin ([`lml_probe.c`](lml_probe.c))

Dans son constructeur (lancé par `module_start` du CRT via `init_array`) :

1. `sceKernelGetModuleInfo(0, …)` → base runtime de l'eboot + **protection de
   chaque segment** (confirme que la vtable est dans un segment **read-only =
   RELRO**).
2. `vtable_VA = seg0.address + 0x066B00F8` (les PT_LOAD sont mappés à
   `base + p_vaddr`, et `p_vaddr(seg0)=0` ⇒ RVA = offset depuis la base seg0).
3. Lecture **seule** des pointeurs de slots et recoupement avec les RVA
   statiques : `slot = expect` → `MATCH`, sinon `DIFF`.

Slots recoupés : 2 (Open), **11 (Read-primitive, off 0x58)**, **13
(Read-forwarder → `+0x68`)**, 17/18 (Seek32/64), 19 (Close), 22/23 (Size32/64),
48 (ReadFull, boucle sur `+0x58`).

**Aucun** `sceKernelMprotect`, **aucun** hook, **aucune** écriture.

## Build / validation conteneur

```powershell
powershell -ExecutionPolicy Bypass -File plugin\tachen\build_probe.ps1
```

Produit `orbis_build\lml_probe_ps4.prx` (≈52944 o), **accepté par le vrai
`tac_prx_inspect`** (rc=0, pas de duplicata de PT_LOAD), même recette que
`lml_plugin.c`.

## Récupérer la sortie

Le plugin écrit sur **deux canaux** :
- `sceKernelDebugOutText` → **klog** (canal primaire, lisible par un viewer klog
  type ps5debug-NG).
- fichiers best-effort `/data/tachen/share/lml_probe.log`, `/data/lml_probe.log`.
  > ⚠️ Le sandbox du jeu jaile `/data` (cf. jalon précédent : le marqueur
  > `lml_bridge_spike.log` n'était pas relisible par FTP). Il est **probable**
  > que ces fichiers ne surfacent pas non plus. **Prévoir un lecteur klog**
  > comme canal de secours fiable.

## Résultat statique déjà acquis (REA/Ghidra)

- **slot 11 = primitive Read moteur** (offset 0x58), wrappée par slot 48
  (ReadFull, boucle sur `*this+0x58`).
- **slot 13 = forwarder** : `(*(*(this+0x10)+0x68))(…)` → délègue au
  device-membre `this+0x10`.
- Le choix **11 vs 13** sur le chemin réel du chargement d'assets story-mode se
  tranche **en live** : c'est l'étape SUIVANTE (compteur non invasif), permise
  seulement une fois ce probe `MATCH` sur toute la ligne.

## Après ce probe (dans l'ordre, chaque étape gated par la précédente)

1. Charger `lml_probe_ps4.prx`, lire le klog : tous les slots en `MATCH`,
   vtable en segment read-only ⇒ **signatures validées live**.
2. Compteur non invasif pour trancher 11 vs 13 sur un chargement story-mode.
3. **Seulement ensuite** : armer le détour (`rdr2_100_packfile_hooks_arm`) sur un
   fichier non critique, toutes ops interceptées, rollback immédiat.
4. Resource replacement RPF8 offline Story.
