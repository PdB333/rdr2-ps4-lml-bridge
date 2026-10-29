# Analyse RAGE VFS de l'eboot PS4 fourni — profil statique

Analyse du 29 octobre 2026. Ce document ne contient PAS le binaire du jeu.

## Identité du fichier

- Fichier utilisateur : eboot.bin, 121 670 745 octets, ELF x86-64 Orbis
- SHA-256 : e3ae087f833b0f30f462bb7f880dd2955bf9f51dbb6e56706ee9bda81581feff
- Format : ELF type 0xFE10, ABI FreeBSD/Orbis, 11 program headers
- La table des sections d'origine est absente : e_shoff pointe au-delà
  du fichier. Les segments de chargement sont toutefois présents.
- IMPORTANT : la version de mise à jour et le Title ID CUSA précis ne
  sont pas prouvés par le simple contenu de cet ELF. Les adresses
  ci-dessous sont valables UNIQUEMENT pour ce SHA-256.

## Classes RTTI et tables virtuelles identifiées

| Classe | RTTI RVA | Vtable RVA | Slot 2 : candidat Open |
| --- | ---: | ---: | ---: |
| rage::fiPackfile8 | 0x066B0480 | 0x066B00F8 | 0x0452A480 |
| rage::fiPackfile7 | 0x066B00D0 | 0x066AFD48 | 0x04522190 |
| rage::fiDeviceLocal | 0x066B1060 | 0x066B0E48 | 0x04533960 |
| rage::fiDeviceRelative | 0x066B0BE0 | 0x066B09C8 | 0x04531BD0 |
| rage::fiDevice (base) | 0x066AFD28 | non isolée | — |

Pour la vtable fiPackfile8 à RVA 0x066B00F8 :

| Slot | RVA | Interprétation |
| --- | --- | --- |
| 0 / 1 | 0x0452A380 / 0x0452A3F0 | destructeurs |
| **2** | **0x0452A480** | Open : this en rdi, chemin en rsi, booléen en dl, handle en rax |
| 6 | 0x0452A780 | ouverture groupée probable |
| 13 | 0x0452B9D0 | lecture probable |
| 14 | 0x0452BA60 | lecture groupée probable |

La fonction fiPackfile8::Open appelle RVA 0x0452E970 pour chercher
une entrée dans le packfile. Les autres slots sont des candidats
nécessitant une analyse ABI plus approfondie. Certaines demandes
peuvent transiter par fiDeviceRelative et perdre le préfixe virtuel
de chemin avant l'ouverture du packfile.

## Profil de compatibilité intégré au PRX

- runtime/rage_eboot_profile.h et .c
- Export Orbis : lml_eboot_verify_profile(callback, context, base, out)
- Compare la chaîne RTTI fiPackfile8, son pointeur typeinfo, six
  pointeurs de fonctions et 16 octets à l'entrée de quatre fonctions.
- Aucun accès mémoire n'est effectué en dehors du callback de lecture,
  qui doit lui-même vérifier que la zone est mappée.
- En cas de mauvais RVA, corruption ou échec de lecture, renvoie une
  erreur et remet les résultats à zéro : **fail closed**.
- Une correspondance ne prouve PAS que le chargement de plugins fonctionne
  sur PS5 13.60, ni que l'interface RPF8 soit correctement détournée.
- Le PRX continue d'annoncer game_hook_installed == 0.

Testé sur cet ELF : réussite, rejet d'un premier octet de fonction
modifié et rejet d'une mauvaise base mémoire.

## Analyse reproductible hors GitHub

Inspecteur : tools/inspect_rdr2_eboot.py (Python standard, lecture seule).

Depuis la racine du projet, en remplaçant le chemin local :

    python -B .\tools\inspect_rdr2_eboot.py MON_EBOOT.bin --expected-sha256 e3ae087f833b0f30f462bb7f880dd2955bf9f51dbb6e56706ee9bda81581feff --out mon_profil_local.json

Le fichier eboot.bin et tout ELF reconstruit doivent rester hors
du dépôt GitHub public. Les scripts n'envoient aucune donnée sur Internet.

## Restant pour un vrai hook RAGE / RPF8

1. Confirmer Title ID et mise à jour 1.32 sur la console ; comparer le
   contenu à cet eboot, sans supposer que les RVA sont universels.
2. Déterminer les vraies signatures d'appel des fonctions read, seek,
   close, size et stat ; ne jamais retourner un token synthétique du
   bridge à une méthode RAGE non détournée.
3. Vérifier le chemin virtuel complet vs relatif effectivement transmis
   à fiPackfile8, notamment pour update:/ et common:/.
4. Vérifier le chargeur de module PS4 sur cette PS5 13.60 et les
   protections mémoire avant une éventuelle modification de vtable.
5. Installer le détournement de manière réversible, uniquement si la
   signature du jeu et de toutes les méthodes attendues correspond.
6. Tester une seule ressource non critique dans le mode Histoire, hors ligne.
   Les ressources RAGE XML/PSO et le streamer requièrent encore une
   sérialisation / un enregistrement spécifique.

**Statut : vraies fonctions RPF8 identifiées statiquement dans l'ELF,
profil de contrôle compilé, mais aucun hook dans le jeu ni test PS5.**

Référence d'interface fiDevice générale (GTA/FiveM, pas PS4 RDR2) :
https://github.com/citizenfx/fivem/blob/master/code/components/rage-device-five/src/fiDeviceClasses.cpp
