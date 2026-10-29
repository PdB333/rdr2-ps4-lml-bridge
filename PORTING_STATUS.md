# LML PS4/PS5 : état du port et points d'intégration

Dernière vérification : 28 octobre 2026.

## Constat

- ModLoader/vfs.asi : module Windows PE x64 de 879 104 octets, sans code source dans ce dossier. REA a observé 21 dépendances DLL, dont MSVC/WinAPI.
- ModLoader/ModManager.Core.dll et ModManager.NativeInterop.dll : assemblages .NET x64.
- ModManager/ModManager.UI.exe : exécutable .NET Framework 4.5 (UI PC, non nécessaire pour le chargement dans RDR2).
- Les install.xml des exemples et les ressources qu'ils nomment peuvent être interprétés indépendamment du programme propriétaire.

## Travail réalisé

1. Compilateur déclaratif : ps4_lml_bridge/compiler.py.
2. Cœur C++17 portable : ps4_lml_bridge/runtime/overlay_index.hpp et overlay_index.cpp.
3. Programme de test Windows : ps4_lml_bridge/runtime/overlay_probe.exe, compilé statiquement.
4. Paquet d'exemples : ps4_lml_bridge/staged_samples_v2, avec 5 mods, 14 ressources et 20 164 930 octets.
5. 42 tests Python/C++ incluant redirection d'octets RAGE VFS, fallbacks RPF, chargement de cartes, exports Orbis et staging etaHEN réussis.
6. Les 14 hashes des ressources copiées correspondent aux sources d'origine.
7. Compilateur croisé OpenOrbis 0.5.4 / LLVM 18.1.8 installé en isolation. Quatre PRX de diagnostic compilés hors console ; les deux nouveaux exportent explicitement module_start, et le runtime C++ peut charger automatiquement le catalogue en lecture seule.
8. Le staging local etaHEN peut préparer un dossier de test pour un Title ID explicitement fourni, sans transfert sur la console.
9. Adaptateur de lecture RAGE/RPF8 (ps4_lml_bridge/runtime/rage_vfs_redirect.h/.cpp) implémenté avec API C, callbacks vers backend original, gestion des handles et métadonnées, et remplacement de chemins de chargeurs texte. Compilation Orbis PRX 18 exports vérifiée ; aucun hook non validé posé dans l'EBOOT.

## Matrice de statut

| Capacité | Statut |
| --- | --- |
| Convertir la déclaration FileReplacement en table portable | Fait / testé |
| Indexer StreamingFile et DataFile | Fait / testé hors jeu |
| Sélectionner un ResourceGroup | Fait / testé |
| Compiler C++17 du résolveur sur Windows | Fait / testé |
| Compiler un module PRX Orbis de diagnostic | Fait / quatre PRX dont les deux derniers exportent module_start |
| Tester le chargement de overlay.map dans un PRX en lecture seule sur PC | Fait / tests de simulation, aucun test sur console |
| Préparer un dossier local pour le chemin game_plugins du Title ID | Fait / deux modes testés ; aucun transfert console |
| Signaler les XML RAGE non convertis | Fait / testé |
| Produire des assets PS4 chargés par le jeu | Non fait |
| Transformer XML (.ymt, .ymap, .ytyp, .ymf) en format reconnu par RDR2 PS4 | Non fait |
| Remplacer les octets sur des appels RAGE VFS simulés | Fait / testé, retour RPF d'origine et cohérence metadata inclus |
| Fournir le corps du hook de chargeurs XML/META/OMT/DAT | Fait / testé hors jeu |
| Compiler un PRX Orbis de l'adaptateur RAGE VFS | Fait / 18 exports API vérifiés |
| Intercepter le vrai jeu RDR2 PS4 1.32 via EBOOT/fiDevice | **Non fait : offsets, signatures et ABI réels non vérifiés** |
| Gérer la registration de data et streaming dans RDR2 PS4 | Non fait |
| Charger un module ou .prx dans le processus PS4 de RDR2 sur PS5 | Non vérifié |
| Convertir directement vfs.asi en PRX | Non fait / non généralisable |

## Contrat d'intégration minimal

Le code portable fournit : une recherche de remplacement par GamePath, une recherche de ressource streaming par nom et une recherche de DataFile par type et nom. Il lit une table de mappings déterministe, refuse les doublons et vérifie l'existence/la taille des fichiers.

Le nouveau corps du hook RAGE VFS (rage_vfs_redirect.cpp) redirige le flux d'octets et les métadonnées avec rappel aux fonctions d'origine en cas d'échec, et peut transmettre un chemin physique pour un chargeur de texte. L'adaptateur propre au jeu doit encore brancher les appels réels de fiDevice de RDR2 PS4 1.32 : sans EBOOT/ELF de cette version et ABI vérifiée, aucun trampoline n'est installé. Pour StreamingFile et DataFile, les enregistrements dans RAGE restent à développer. Aucun offset PS4 1.32 n'a été inventé.

**Cible établie :** RDR2 PS4 version 1.32 sur PS5 firmware 13.60 jailbreakée. Le toolchain Orbis est installé localement et les PRX sont compilés. Le chargement réel dans le processus de RDR2 n'a pas été validé. Un problème mprotect a été signalé en octobre 2026 pour CUSA08519 sur 13.60. Voir orbis/CONSOLE_DIAGNOSTIC.md et orbis/README_PS5_1360.md. Un PRX Orbis compilé ne constitue pas à lui seul un modloader intégré au jeu.

Le projet ne prétend donc pas être directement installable sur console et ne contient aucun code propriétaire de LML. Les cinq PRX restent des modules de diagnostic et de développement hors jeu, y compris rage_vfs_adapter qui contient le moteur de redirection sans le hook EBOOT. Les sondes C et C++ permettent de distinguer échec du chargeur, lecture de la map et initialisation du runtime. Voir orbis/RAGE_VFS_132_PORT.md.
