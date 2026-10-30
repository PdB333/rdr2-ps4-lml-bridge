# LML PS4/PS5 : état du port et points d'intégration

Dernière vérification : 30 octobre 2026.

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
5. 68 tests Python/C++ incluant redirection d'octets RAGE VFS, fallbacks RPF, chargement de cartes, exports Orbis et staging etaHEN réussis.
6. Les 14 hashes des ressources copiées correspondent aux sources d'origine.
7. Compilateur croisé OpenOrbis 0.5.4 / LLVM 18.1.8 installé en isolation. Quatre PRX de diagnostic compilés hors console ; les deux nouveaux exportent explicitement module_start, et le runtime C++ peut charger automatiquement le catalogue en lecture seule.
8. Le staging local etaHEN peut préparer un dossier de test pour un Title ID explicitement fourni, sans transfert sur la console.
9. Adaptateur de lecture RAGE/RPF8 (ps4_lml_bridge/runtime/rage_vfs_redirect.h/.cpp) implémenté avec API C, callbacks vers backend original, gestion des handles et métadonnées, et remplacement de chemins de chargeurs texte. Compilation Orbis PRX 19 exports vérifiée ; aucun hook non validé posé dans l'EBOOT.

11. **RDR2 PS4 1.00 en priorité :** PRX indépendant `LmlBridge_RDR2_PS4_100_fiPackfile8_trace.prx` construit avec 13 exports. Profil EBOOT 1.00, contrôle FNV des 112 méthodes virtuelles, trace Open par vtable privée d'une seule instance, retrait conditionnel et permanence du module après activation. Stress multithread hôte + exceptions vérifiés. **Mode passif par défaut, aucun hook automatique ni remplacement in-game.** Voir `orbis/RDR2_PS4_100_TRACE_STATUS.md`.

12. **Préparation de l'installation RDR2 PS4 1.00 :** documentation FTP etaHEN Unified dans `orbis/INSTALL_PS5_100.md` ; script `orbis/stage_pack_trace_100.py` produit uniquement un dossier local après saisie du vrai CUSA, contrôle SHA-256 et verrouillage du profil 1.00. Aucune connexion PS5 ni installation sur console n'a été effectuée. Cinq tests de staging spécifiques passent.

13. **Liaison réseau ps5debug-NG / configuration réelle Y2JB + Kstuff Lite + ShadowMountPlus :** aucun etaHEN n'est installé. Le poste Windows dispose d'un accès LAN Ethernet et le client `tools/ps5debug_ng_probe.py` réalise une découverte UDP 1010 optionnelle et le protocole branding/firmware TCP 744 en lecture seule, sans modification PS5. Neuf tests hors réseau valident le protocole. Voir `orbis/PS5DEBUG_NG_LOCAL_NETWORK.md`. L'utilisateur doit encore lancer le payload sur la PS5 et confirmer la connexion réelle.

## Matrice de statut

| Capacité | Statut |
| --- | --- |
| Convertir la déclaration FileReplacement en table portable | Fait / testé |
| Indexer StreamingFile et DataFile | Fait / testé hors jeu |
| Sélectionner un ResourceGroup | Fait / testé |
| Compiler C++17 du résolveur sur Windows | Fait / testé |
| Compiler un module PRX Orbis de diagnostic | Fait / six PRX locaux, dont un traceur réservé à PS4 1.00 |
| Préflight vtable fiPackfile8 1.00 / 112 slots | Fait / code et tests positifs/négatifs hors console |
| Tracer Open sur un objet de test concurrent | Fait / trace réversible, conservation des handles originaux |
| Brancher le traceur au processus réel RDR2 1.00 | **Non fait / pas de test console** |
| Tester le chargement de overlay.map dans un PRX en lecture seule sur PC | Fait / tests de simulation, aucun test sur console |
| Préparer un dossier local pour le chemin game_plugins du Title ID | Fait / deux modes testés ; aucun transfert console |
| Signaler les XML RAGE non convertis | Fait / testé |
| Produire des assets PS4 chargés par le jeu | Non fait |
| Transformer XML (.ymt, .ymap, .ytyp, .ymf) en format reconnu par RDR2 PS4 | Non fait |
| Remplacer les octets sur des appels RAGE VFS simulés | Fait / testé, retour RPF d'origine et cohérence metadata inclus |
| Fournir le corps du hook de chargeurs XML/META/OMT/DAT | Fait / testé hors jeu |
| Compiler un PRX Orbis de l'adaptateur RAGE VFS | Fait / 19 exports API vérifiés |
| Intercepter le vrai jeu RDR2 PS4 1.32 via EBOOT/fiDevice | **Non fait : offsets, signatures et ABI réels non vérifiés** |
| Gérer la registration de data et streaming dans RDR2 PS4 | Non fait |
| Charger un module ou .prx dans le processus PS4 de RDR2 sur PS5 | Non vérifié |
| Convertir directement vfs.asi en PRX | Non fait / non généralisable |

## Contrat d'intégration minimal

Le code portable fournit : une recherche de remplacement par GamePath, une recherche de ressource streaming par nom et une recherche de DataFile par type et nom. Il lit une table de mappings déterministe, refuse les doublons et vérifie l'existence/la taille des fichiers.

Le nouveau corps du hook RAGE VFS (rage_vfs_redirect.cpp) redirige le flux d'octets et les métadonnées avec rappel aux fonctions d'origine en cas d'échec, et peut transmettre un chemin physique pour un chargeur de texte. L'adaptateur propre au jeu doit encore brancher les appels réels de fiDevice de RDR2 PS4 1.32 : l'ELF fourni est maintenant analysé statiquement (SHA-256 e3ae087f833b0f30f462bb7f880dd2955bf9f51dbb6e56706ee9bda81581feff) et ses RTTI/vtables fiPackfile8 donnent des RVA candidats. L'utilisateur a confirmé que cet EBOOT est **PS4 1.00** et NON 1.32. Son Title ID CUSA, les ABI des autres méthodes et l'exécution en jeu restent non confirmés ; aucun trampoline n'est installé. Pour StreamingFile et DataFile, les enregistrements dans RAGE restent à développer. Ces adresses dérivent exclusivement de l'EBOOT **1.00** : elles sont invalides comme profil de référence pour la version **1.32** tant qu'un EBOOT 1.32 n'a pas été analysé.

**Priorité utilisateur établie :** RDR2 PS4 **1.00 d'abord**, ensuite 1.32, sur PS5 firmware 13.60 jailbreakée. Le toolchain Orbis est installé localement et les PRX sont compilés. Le chargement réel dans le processus de RDR2 n'a pas été validé. Un problème mprotect a été signalé en octobre 2026 pour CUSA08519 sur 13.60. Voir orbis/CONSOLE_DIAGNOSTIC.md et orbis/README_PS5_1360.md. Un PRX Orbis compilé ne constitue pas à lui seul un modloader intégré au jeu.

Le projet ne prétend donc pas être directement installable sur console et ne contient aucun code propriétaire de LML. Les six PRX restent des modules de diagnostic et de développement hors jeu ; le nouveau traceur 1.00 ne modifie pas de pointeur du jeu au démarrage et rage_vfs_adapter contient le moteur de redirection sans le hook EBOOT. Les sondes C et C++ permettent de distinguer échec du chargeur, lecture de la map et initialisation du runtime. Voir orbis/RAGE_VFS_132_PORT.md.

10. Profil EBOOT **RDR2 PS4 1.00** (version confirmée par l'utilisateur), lecture seule compilée dans le PRX : lml_eboot_verify_profile exige version 1.00 et refuse 1.32 sans fournir d'adresse. Les tests de code modifié et de simulation hôte passent. Voir orbis/EBOOT_RAGE_VFS_PROFILE.md. Aucun binaire du jeu dans le dépôt.
