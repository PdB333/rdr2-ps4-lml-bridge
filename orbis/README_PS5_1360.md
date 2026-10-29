# RDR2 PS4 1.32 sur PS5 firmware 13.60 — LML Bridge Orbis

État vérifié : 28 octobre 2026. Ce projet ne constitue **pas encore un modloader actif dans le jeu**.

## Cible et format

- Red Dead Redemption 2 **édition PS4, mise à jour 1.32** (dernière version PS4 documentée par Rockstar à cette date).
- PS5 **13.60 jailbreakée** ; c'est un firmware système, pas la version du jeu.
- Le code chargé dans le jeu PS4 en rétrocompatibilité doit cibler **Orbis / PS4**, et non PE64 Windows ou PS5 natif.
- Title IDs connus dans des projets RDR2 1.32 : CUSA03041, CUSA08519, CUSA08568. Le Title ID exact de la console n'est pas présumé.

## Build Orbis effectué

Outils installés localement, sans modifier le PATH global :

- SDK OpenOrbis v0.5.4 sous ps4_lml_bridge/.toolchains/OpenOrbis/PS4Toolchain
- LLVM/Clang 18.1.8 sous ps4_lml_bridge/.toolchains/llvm18-minimal/bin
- Script de build : ps4_lml_bridge/orbis/build_orbis.ps1
- Code de l'interface Orbis : ps4_lml_bridge/orbis/lml_bridge_exports.cpp
- Source indépendante du moteur C++ : ps4_lml_bridge/runtime/overlay_index.cpp
- CRT OpenOrbis pour modules PS4 : lib/crtlib.o fourni par le SDK

Dans un PowerShell ouvert à la racine du dossier modloader :

    powershell -NoProfile -ExecutionPolicy Bypass -File .\ps4_lml_bridge\orbis\build_orbis.ps1

Produit :

    ps4_lml_bridge\orbis_build\LmlBridge_132_api_probe.prx

Le fichier est réellement généré avec le format **Orbis SELF/PRX** par OpenOrbis. Les sept symboles C exportés dynamiquement sont : lml_bridge_abi_version, lml_bridge_open, lml_bridge_lookup_replace, lml_bridge_lookup_stream, lml_bridge_lookup_data, lml_bridge_get_counts, lml_bridge_get_last_error.

Le script vérifie la signature SELF, le SHA-256 et les sept exports. La suite de tests recoupe ces vérifications et teste les résolutions avec le même code C sur un exécutable hôte Windows.

**Fonction réalisée :** bibliothèque native qui associe les chemins virtuels LML aux assets présents dans un dossier préparé, avec lecture des remplacements, des fichiers en streaming et des déclarations DataFile.

**Non réalisé :** interception RAGE/RPF, activation automatique de mods au lancement du jeu, modification du code ou de la mémoire du jeu, validation sur console, remplacement de vfs.asi.

## Compatibilité du chargeur PS5 13.60

Le port communautaire **non officiel** etaHEN 2.5B Unified r1 annonce la prise en charge de 13.60 et du chargement de plugins de jeux PS4 et PS5. L'emplacement annoncé des modules de jeux est :

    /data/etaHEN/game_plugins/<TITLEID>/

Ce chemin est spécifique à cet etaHEN. Une PS5 jailbreakée ne garantit pas que ce port ni que son mécanisme de plugins soit utilisé.

Le ticket **GronedWaffel/etahen-11.00-13.60#8**, ouvert le 25 octobre 2026, décrit un échec de chargement PRX sur **RDR2 PS4 1.32, CUSA08519, PS5 13.60** (erreur arena mprotect). Aucun correctif vérifié n'était indiqué au moment de cet examen. C'est un rapport ciblé, pas la preuve d'un échec pour tous les Title IDs et chargeurs.

Un payload **ELF PS5 externe** est une autre piste technique : armanate/rdr2-60fps-runtime-patcher agit sur la mémoire de RDR2 1.32 sous 13.60. Mais il ne fournit pas de chargement d'assets RAGE ni de modloader LML.

## Travail restant pour le modloader en jeu

1. Confirmer qu'un plugin Orbis minimal peut réellement être chargé dans RDR2 sur cette PS5 avec les logs du chargeur. La compilation sur PC ne suffit pas.
2. Connecter les appels au VFS interne **RAGE/RPF8** de la version PS4 1.32. Les chemins RPF comme update:/... ne sont pas de simples chemins POSIX.
3. Implémenter l'enregistrement des ressources DataFile et StreamingFile, puis le remplacement des fichiers du jeu, sans supposer que les archives RPF sont modifiables sur le disque.
4. Traduire ou faire reconnaître par le moteur les 9 ressources RAGE/XML, 3 fichiers meta XML, 1 table gxt2 texte et 1 texture RSC8 déjà catalogués.
5. Vérifier les permissions de lecture des données du jeu depuis le sandbox du processus PS4. Le dossier /data/etaHEN n'est pas automatiquement accessible par chaque jeu.

Le fichier PRX se nomme volontairement **api_probe** : il sert au diagnostic du chargeur et de l'interface native. Ce n'est pas une version LML prête à installer en jeu.

## Références publiques

- Rockstar : https://support.rockstargames.com/articles/4GR27mnSMJaPqF5gl2zDNu/red-dead-redemption-2-title-update-1-32-notes-ps4-xbox-one-pc
- OpenOrbis : https://github.com/OpenOrbis/OpenOrbis-PS4-Toolchain
- Port communautaire etaHEN : https://github.com/GronedWaffel/etahen-11.00-13.60/releases
- Ticket loader RDR2/13.60 : https://github.com/GronedWaffel/etahen-11.00-13.60/issues/8
- Payload externe RDR2 1.32 : https://github.com/armanate/rdr2-60fps-runtime-patcher
- Plugin RDR2 PS4 utilisant les natives : https://github.com/ricardoofnl/rdr2-satchel-remover

Le code et les fichiers de build sont indépendants des binaires propriétaires LML. Aucun fichier original modloader n'a été modifié.

## Mise à jour du diagnostic (28 octobre 2026)

Deux PRX supplémentaires sont compilés : LmlBridge_132_readonly_diagnostic.prx (module_start exporté, log noyau, lecture seule de la map) et LmlBridge_132_runtime_probe.prx (runtime C++ et chargement automatique de la map). Le protocole recommandé se trouve dans orbis/CONSOLE_DIAGNOSTIC.md. Il est préférable aux anciennes sondes qui ne permettaient pas de savoir si module_start avait été exécuté. Les 39 tests hors console passent ; aucun test PS5 ni hook RAGE/RPF n'a été effectué.
