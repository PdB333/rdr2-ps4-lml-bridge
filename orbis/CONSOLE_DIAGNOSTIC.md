# RDR2 1.32 PS4 sur PS5 13.60 — protocole de test LML Bridge

État : 28 octobre 2026. **Aucun test exécuté sur la console.**
Les PRX sont expérimentaux ; ce ne sont ni une conversion du vfs.asi
propriétaire ni un modloader fonctionnel en jeu.

## Modules compilés

| Module Orbis | But | Dépendances |
| --- | --- | --- |
| LmlBridge_132_readonly_diagnostic.prx | Exporte module_start, journalise son lancement, lit en lecture seule overlay.map, compte R/S/D ; ne bloque pas le démarrage si le fichier manque | libkernel seulement |
| LmlBridge_132_runtime_probe.prx | Exporte module_start, initialise le runtime C++17 et le résolveur LML ; charge overlay.map ; expose l'API lml_bridge_lookup_* | libkernel, libc++ et libSceLibcInternal |

Le second PRX est plus lourd : il ne doit être tenté qu'après le premier.
Aucun des modules ne contient de hook du moteur RAGE/RPF, ni de patch
mémoire, ni de code de modification des fichiers de jeu.

## Étape 1 : vérifier le module minimal

Dans PowerShell, depuis le dossier modloader, avec le Title ID exact
du jeu PS4 sur la console (CUSA12345 ci-dessous est un exemple fictif) :

    python -B .\ps4_lml_bridge\orbis\stage_etaHEN_probe.py --title-id CUSA12345 --mode diagnostic --out .\ps4_lml_bridge\diag-local-test

La commande refuse d'écraser un dossier existant. Elle prépare
uniquement un répertoire local et n'accède pas à la PS5.

Pour la variante etaHEN qui accepte les game plugins, copier
manuellement, sans écraser d'autres plugins, les deux fichiers :

    /data/etaHEN/game_plugins/<TITLEID>/LmlBridge_132_readonly_diagnostic.prx
    /data/etaHEN/lml_bridge/overlay.map

Fermer RDR2, n'armer que cette sonde dans etaHEN Game Plugins si
disponible, puis lancer le mode Histoire hors ligne.

Messages prévus dans les logs du noyau (s'ils sont collectés) :

    [LML-ORBI-DIAG] MODULE_ENTRY RDR2-PS4-1.32 PS5-13.60
    [LML-ORBI-DIAG] MAP_OK R=0 S=0 D=0

MAP_UNAVAILABLE indique que le module a tourné mais ne peut pas ouvrir
la map au chemin attendu (fichier absent ou sandbox).
MAP_BAD_HEADER, MAP_BAD_RECORD, MAP_LIMIT indiquent un contenu invalide.
Aucun message ne prouve pas l'échec du module : le canal
sceKernelDebugOutText peut ne pas être capturé.

## Étape 2 : essayer le runtime C++ seulement si le chargement fonctionne

Générer un AUTRE dossier local :

    python -B .\ps4_lml_bridge\orbis\stage_etaHEN_probe.py --title-id CUSA12345 --mode runtime --out .\ps4_lml_bridge\runtime-local-test

Désactiver et retirer d'abord le PRX diagnostic du dossier de plugins.
Ne charger qu'un PRX à la fois. La map du test est volontairement vide.

Messages prévus :

    [LML-ORBI-RUNTIME] MODULE_ENTRY RDR2-PS4-1.32
    [LML-ORBI-RUNTIME] MAP_LOADED R=0 S=0 D=0

Sinon : MAP_UNAVAILABLE_OR_INVALID. Ces messages confirmeraient
l'initialisation C++ et le chargement du catalogue, PAS le remplacement
de fichiers dans le jeu. À la fin, désactiver le plugin et fermer le jeu.

## Limite connue sur cette configuration

Le port non officiel etaHEN 2.5B Unified r1 annonce les game plugins PRX
pour PS4/PS5 firmware 13.60 ; ce support n'est pas universel.

Le 25 octobre 2026, un ticket encore ouvert signale un échec du
chargeur (arena mprotect) sur RDR2 PS4 1.32 CUSA08519 / PS5 13.60.
Si le loader échoue avant MODULE_ENTRY, ce n'est pas un problème du
parseur LML. Ne pas essayer de contourner aveuglément les protections
mémoire. La PS5 peut également utiliser un jailbreak sans ce port etaHEN.

## Pour obtenir le vrai modloader

1. Valider le chargement PRX dans le processus RDR2, version PS4 1.32.
2. Trouver une interface RAGE/RPF8 documentée et stable pour les chemins
   virtuels update:/..., puis raccorder lml_bridge_lookup_replace.
3. Ajouter l'enregistrement de ressources StreamingFile et DataFile.
4. Interpréter ou convertir les fichiers XML RAGE/PSO et chaînes .gxt2,
   qui ne sont pour l'instant que catalogués.
5. Valider en jeu un seul remplacement réversible, sans jeu en ligne.

## Commandes de compilation et test sur le PC

    powershell -NoProfile -ExecutionPolicy Bypass -File .\ps4_lml_bridge\orbis\build_readonly_diag.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File .\ps4_lml_bridge\orbis\build_runtime_probe.ps1
    python -B -m unittest discover -s .\ps4_lml_bridge\tests -p test_*.py -v

## Sources publiques

- OpenOrbis : https://github.com/OpenOrbis/OpenOrbis-PS4-Toolchain
- etaHEN Unified, port non officiel : https://github.com/GronedWaffel/etahen-11.00-13.60
- Incident RDR2 13.60 : https://github.com/GronedWaffel/etahen-11.00-13.60/issues/8
- Exemple sur module_start exporté : https://github.com/hudsonbrendon/ps4-mqtt-plugin

Une PS5 jailbreakée reste un environnement à risques. Préserver les
sauvegardes et les autres plugins, procéder hors ligne et garder les
tests réversibles. Ce projet ne contrôle pas directement la console.

## Nouveau composant RAGE VFS (non activé dans le jeu)

Le fichier ps4_lml_bridge/orbis_build/LmlBridge_132_rage_vfs_adapter.prx possède 18 fonctions API exposées. Il sait lire et remplacer les octets de fichiers sur une API virtuelle testée et retourner au fichier RPF8 original en cas d'erreur ; le chargement automatique ne pose toutefois **aucun hook dans RDR2**. Ne pas installer ce PRX à la place des deux sondes pour obtenir des mods : cela ne changerait pas les données du jeu. Consulter orbis/RAGE_VFS_132_PORT.md pour les conditions d'un hook réel avec EBOOT PS4 1.32 vérifié.
