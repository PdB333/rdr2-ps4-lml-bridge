# Installer et charger le plugin `.prx` via TacHen (RDR2 PS4 1.00)

Procédure de chargement sur la vraie console. Chaque étape est tirée du dépôt
TacHen (`README.md`, `docs/PRX-CONTAINER-COMPATIBILITY.md`) — **rien n'est
deviné**. Ce qui n'est pas encore prouvé sur console est signalé « À VÉRIFIER ».

## 0. Pré-requis

- PS5 **FW 13.40**, jailbreak Y2JB + Kstuff Lite + ShadowMountPlus + Payload
  Manager (le setup du propriétaire). TacHen est compatible 13.40.
- Le `.prx` produit par [`build_ps4.ps1`](build_ps4.ps1) : `lml_plugin_ps4.prx`
  (52736 o, magic `0x1d3d154f`), PRX PS4 OpenOrbis déjà accepté par le
  validateur `tac_prx_inspect` (sans duplicata de PT_LOAD).
- RDR2 **CUSA08519, version 01.00 exacte** installé.

## 1. Lancer TacHen

1. Récupérer **`TacHen.elf`** (Beta 1) depuis les Releases officielles. La
   variante `TacHen-compatibility.elf` n'est nécessaire que pour les plugins
   **GoldHEN** (pont syscall-500, ex. Havana). Notre plugin n'utilise que des
   imports libc standard → **`TacHen.elf` Beta 1 suffit**.
2. Rebooter + jailbreaker la PS5. Envoyer l'ELF via le Payload Manager (ou le
   sender habituel). Attendre la notification de démarrage.
3. Ouvrir l'interface : manette **L3 + R3**, ou le web **`http://IP-PS5:8780`**
   depuis un PC/téléphone sur le même réseau.

## 2. Copier le `.prx` sur la console

Au choix :

- **Clé USB** : copier `lml_plugin_ps4.prx` sur une clé, la brancher.
- **FTP TacHen** : port **2122**, racine `/data/tachen/share`, login `tachen`
  ou `anonymous` (n'importe quel mot de passe), réseau local de confiance.
- **Onglet Transfers** du web TacHen : navigateur deux volets USB ↔ stockage
  console.

> On **ne dépose pas** le fichier à la main dans
> `/data/tachen/module-files/...` : ce chemin est la zone de staging interne de
> TacHen (montée en lecture seule sur `/tachen-modules` dans le jeu). TacHen y
> recopie le module lui-même après l'import de l'étape 3.

## 3. Importer et enregistrer le plugin

Dans **Plugins** (manette ou web) :

1. **Add from storage** / importer → sélectionner `lml_plugin_ps4.prx` (USB ou
   stockage console).
2. **Enregistrer pour le jeu et la version** : choisir **RDR2 CUSA08519**,
   version **01.00**. C'est le jeu sélectionné qui fixe la plateforme : le magic
   `0x1d3d154f` est traité comme « plateforme non spécifiée », donc RDR2 étant un
   titre PS4, le module est validé en **PS4**. L'enregistrement est par jeu +
   version **exacte**.

Si l'import est refusé, TacHen affiche l'erreur détaillée (ex. tailles
déclarée/réelle). Ne pas renommer/tronquer le `.prx` pour contourner un
contrôle — corriger le build.

## 4. Lancer le jeu, PUIS charger le plugin

L'autostart des plugins a été retiré par TacHen (« It's recommended to not start
plugins until you are in game »).

1. Lancer **RDR2 1.00**, laisser charger le **mode Story**.
2. Dans **Plugins**, charger manuellement `lml_plugin_ps4` (ou via un loadout).
3. TacHen crée un pthread appartenant au jeu et y exécute `module_start`
   (retour non nul = échec ; un échec/timeout reste suivi jusqu'à la fermeture
   du jeu). Un éventuel couple `plugin_load`/`plugin_unload` servirait
   d'activation — notre plugin n'en a pas, donc `module_start` seul suffit.

## 5. Vérifier la preuve de vie

`module_start` écrit une ligne horodatée :

```
[LML] <timestamp> module_start: notre code tourne dans le process RDR2 1.00
```

Deux sources de vérification :

- **`runtime.log` de TacHen** (source de vérité primaire) : journalise
  l'enregistrement, les transitions d'étape du module natif et le résultat de
  l'initialiseur. **Vérifié console (2 nov. 2026, FTP port 2121 racine)** :
  plusieurs `game.module.start status=completed phase=module-started`
  (CUSA08519 01.00, pid 109/235), **aucun `0x80020016`**. Un dernier essai
  `MODULE_ALREADY_ATTEMPTED` = normal (fermer RDR2 entre essais).
- **`/data/tachen/modules/<hash>.session`** : pour le hash de notre PRX,
  contient **« Module initializer completed; no paired plugin activation
  exports »** → `module_start` (CRT) a parcouru `init_array` jusqu'au bout, donc
  notre constructeur s'est exécuté. « no paired exports » = normal (pas de
  `plugin_load/unload`).
- **Notre marqueur** `/data/lml_bridge_spike.log` : **ABSENT en pratique.** Le
  plugin tourne dans le **sandbox du jeu** qui jaile `/data` (visibilité + quota
  tmpfs). Les 3 chemins candidats (`lml_plugin.c`) n'ont pas produit de fichier
  relisible par FTP. Ce n'est **pas** un échec du jalon : le marqueur fichier
  n'est pas le juge, `runtime.log` + `.session` le sont. Le canal
  `sceKernelDebugOutText` n'est pas relisible par FTP non plus.

## 6. Interprétation honnête

- `module_start` renvoie 0 **+ ligne présente** = jalon atteint : **notre code
  s'exécute dans RDR2 1.00**. C'est la seule preuve console valable ; la
  validation `tac_prx_inspect` côté PC ne prouvait que le conteneur.
- Un crash du jeu, un `module_start` non nul, un timeout, ou l'absence de ligne
  = **échec** : capturer `runtime.log` et, s'il existe, le log du jeu, puis
  diagnostiquer. Ne jamais présenter un succès de conteneur ou un test simulé
  comme un succès en jeu.
- Tant que ce jalon n'est pas atteint, **ne pas** greffer l'armement du détour
  `fiPackfile8` (`rdr2_100_packfile_hooks_arm`) dans `module_start` : il reste
  interdit jusqu'à validation live des signatures.

## 7. Après le jalon (pas avant)

1. Valider en live l'ABI `fiPackfile8` (vtable en zone RELRO, slots close/seek/
   size, Read 11 vs 13) — cf. `orbis/LIVE_DETOUR_100.md`.
2. Seulement ensuite : armer le détour sur un objet, un fichier non critique,
   avec rollback immédiat, en interceptant **toutes** les opérations (Read,
   Seek, Size, Stat, Close), jamais `Open` seul.
