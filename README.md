# RDR2 LML Bridge — prototype indépendant pour un futur port PS4/PS5

État au 28 octobre 2026. Ce projet **n'est pas un vfs.asi converti en .prx** et ne fonctionne pas encore dans RDR2 sur console. Il porte uniquement la partie indépendante du moteur : lecture de descriptions de mods, préparation des ressources et correspondance de chemins.

Cible : RDR2 **version PS4 1.32**, sur **PS5 jailbreakée firmware 13.60**.

## Fichiers

- compiler.py : lit les install.xml, valide et prépare des dossiers d'assets, sans exécuter les binaires d'origine
- runtime/overlay_index.hpp et runtime/overlay_index.cpp : moteur C++17 portable de résolution de chemins, sans dépendances Windows ni injection dans le jeu
- runtime/overlay_probe.cpp : banc de test Windows du moteur C++, pas un exécutable PlayStation
- tests/ : 42 tests de parsing LML, redirection RAGE/VFS, sécurité des chemins, contrat ABI, staging etaHEN et structure PRX Orbis
- staged_samples_v2/catalog.json : catalogue complet des ressources et avertissements d'intégration
- staged_samples_v2/overlay.map : table compacte pour le moteur C++ portable
- staged_samples_v2/payload : copies octet pour octet des 14 ressources d'exemple
- orbis/build_orbis.ps1 et orbis/build_loader_smoke.ps1 : compilation croisée PS4 avec OpenOrbis et Clang
- orbis_build/LmlBridge_132_api_probe.prx : module PS4 de diagnostic avec sept fonctions de résolution de fichiers exportées
- orbis_build/LmlBridge_132_loader_smoke.prx : ancien module PS4 minimal sans hook (supplanté pour les nouveaux tests)
- orbis_build/LmlBridge_132_readonly_diagnostic.prx : nouvelle sonde C avec module_start exporté, logs noyau et lecture seule du fichier overlay.map
- orbis_build/LmlBridge_132_runtime_probe.prx : nouvelle sonde C++17 avec module_start exporté, chargement du catalogue et API de résolution LML
- orbis/stage_etaHEN_probe.py : crée un dossier local etaHEN pour un Title ID CUSA explicite (mode diagnostic puis runtime), sans connexion console
- orbis/CONSOLE_DIAGNOSTIC.md : mode opératoire, journaux attendus, problème connu du chargeur RDR2 13.60
- runtime/rage_vfs_redirect.h et .cpp : moteur C++17 d'interception des opérations virtuelles (open/read/read_at/seek/size/close/stat) et substitution des chemins XML/META/OMT/DAT, avec retour aux appels RPF8 d'origine
- runtime/rage_vfs_harness.cpp : vrai remplacement d'octets simulé avec faux backend RPF8, tests de repli, tailles et handles
- orbis_build/LmlBridge_132_rage_vfs_adapter.prx : adaptateur Orbis compilé avec 18 symboles exportés, **sans installation de hook dans le véritable EBOOT du jeu**
- orbis/RAGE_VFS_132_PORT.md : architecture détaillée du hook RAGE, limites des formats et prérequis exacts de la version PS4 1.32

Les fichiers originaux ModLoader/vfs.asi, ModManager.* et les autres binaires n'ont pas été modifiés.

## Tests réels

Cinq exemples convertis, soit 14 ressources et 20 164 930 octets, vérifiés par SHA-256 contre leurs sources.

| Fonction | Résultat |
| --- | ---: |
| FileReplacement | 8 chemins |
| StreamingFile | 2 fichiers |
| DataFile | 4 déclarations |
| Tests Python, C++, VFS/RPF8 simulé et structure PRX (hors console) | 42 réussis |

Classification du contenu :
- 9 ressources .ymt/.ymap/.ytyp/.ymf contenant du XML (sérialisation/compatibilité RAGE-PSO manquante)
- 3 fichiers .meta XML (parseur moteur à vérifier)
- 1 fichier .gxt2 en texte LML (enregistrement des chaînes non réalisé)
- 1 fichier .ytd commençant par RSC8 (compatibilité de ressource sur console non testée)

**Important : le compilateur préserve les octets d'origine ; il ne convertit pas les XML en ressources RAGE binaires.** La publication officielle de LML indique que le chargeur PC réalise des adaptations de données et du chargement PSO/XML. Cette fonction reste à refaire pour la version PS4 du jeu.

## Utilisation sur le PC

Depuis PowerShell, dans le dossier :
Clone this repository to a local workspace; its directory depends on your machine.

Prévisualiser sans créer de fichiers :

    python -B .\ps4_lml_bridge\compiler.py --source . --dry-run --all-groups

Générer un nouveau paquet (le dossier doit être inexistant) :

    python -B .\ps4_lml_bridge\compiler.py --source . --out .\ps4_lml_bridge\mon_paquet --all-groups

Sélectionner un seul groupe au lieu de les activer tous :

    python -B .\ps4_lml_bridge\compiler.py --source . --out .\ps4_lml_bridge\mon_paquet --group "More assertive peds"

Compiler le résolveur de test sur le PC :

    g++ -std=c++17 -O2 -Wall -Wextra -Werror -static -static-libgcc -static-libstdc++ .\ps4_lml_bridge\runtime\overlay_index.cpp .\ps4_lml_bridge\runtime\overlay_probe.cpp -o .\ps4_lml_bridge\runtime\overlay_probe.exe

Vérifier un remplacement :

    .\ps4_lml_bridge\runtime\overlay_probe.exe .\ps4_lml_bridge\staged_samples_v2 replace "update:/common/data/ai/combatbehaviour.meta"

Tester tout le projet :

    python -B -m unittest discover -s .\ps4_lml_bridge\tests -p "test_*.py" -v

Les types pris en charge par ce prototype sont FileReplacement, StreamingFile, DataFile et ResourceGroups (opt-in). Les autres fonctionnalités de install.xml, en particulier FileEntryReplacement, StreamingFiles, DataFiles, DLC complexes, et les dossiers historiques stream/replace sans manifeste, ne sont pas encore prises en charge. Le programme rejette explicitement les fonctionnalités inconnues, les fichiers manquants, les conflits de destinations, les accès hors dossier et les XML dangereux.

## Éléments manquants pour un vrai chargeur sur PS5

1. **Vérifier sur PS5 13.60** le chargement d'un PRX minimal dans RDR2 PS4 1.32. Un signalement du 25 octobre 2026 décrit une erreur mprotect dans le chargeur etaHEN pour RDR2 CUSA08519.
2. **Compilation PS4/Orbis réalisée :** OpenOrbis 0.5.4 et LLVM 18.1.8 produisent les deux sondes nouvelles avec module_start exporté. Le chargement réel dans le jeu reste non testé.
3. **RAGE VFS : adaptateur de remplacement développé et testé hors jeu.** Pour activer son hook dans le jeu PS4 1.32, il reste à identifier les méthodes RAGE de cette version dans l'EBOOT/ELF et à implémenter le trampoline avec vérification des signatures et des handles. Le fichier update:/... n'est pas un chemin POSIX.
4. Fournir la capacité de déclarer les assets en streaming et les types de DataFile dans le moteur RDR2, ainsi que les ressources XML/RAGE/PSO et tables de chaînes.
5. Tester un seul remplacement réversible dans RDR2 en mode histoire, hors ligne, avant d'ajouter les autres fonctions.

Cinq PRX de diagnostic/développement existent dont le nouvel adaptateur rage_vfs_adapter. Le remplaçant VFS donne réellement les octets moddés **lorsqu'il reçoit des appels par l'ABI testée**, mais aucun hook n'a été posé dans l'EBOOT RDR2 1.32. Aucun **modloader PRX fonctionnel dans le vrai jeu**, test sur console ou validation des ressources PS4 n'a été réalisé. Voir orbis/RAGE_VFS_132_PORT.md et orbis/CONSOLE_DIAGNOSTIC.md.

## Droits / provenance

La licence du package d'origine (modloader/license.txt) interdit la modification, le désassemblage et la redistribution des binaires LML. Le prototype est une réimplémentation **indépendante** basée sur les exemples install.xml et la documentation publique ; il ne recopie pas le binaire ni les DLL de Lenny's Mod Loader.

Conserver les fichiers et mods d'exemple localement, sans les redistribuer hors des droits qui leur sont propres.

Documentation publique :
- https://www.rdr2mods.com/downloads/rdr2/tools/76-lennys-mod-loader-rdr/
- https://www.lcpdfr.com/wiki/lml/installxml-r68/
- https://github.com/OpenOrbis/OpenOrbis-PS4-Toolchain
