# Ancienne procedure etaHEN (non applicable a la console actuelle)

**IMPORTANT : cette procedure historique concerne etaHEN Unified sur
PS5 13.60.** La console du proprietaire est maintenant confirmee
**PS5 13.40 avec Y2JB + Kstuff Lite + ShadowMountPlus, sans etaHEN**.
**Ne pas utiliser le chemin de plugins etaHEN decrit ci-dessous.**
Pour la connexion actuelle voir orbis/PS5DEBUG_NG_LOCAL_NETWORK.md.
Un chargeur de PRX directement dans RDR2 n'est PAS encore disponible
sur cette configuration.

# Installer le PRX RDR2 PS4 1.00 — PS5 13.60 (etaHEN uniquement)

## Important : premier test, pas encore un modloader

Le fichier LmlBridge_RDR2_PS4_100_fiPackfile8_trace.prx est une
**sonde passive de chargement Orbis** compilée et testée sur Windows.
Elle ne pose **aucun hook en jeu** et n'active **aucun mod LML**.
Elle n'affiche ni menu ni notification graphique et ne modifie pas
le jeu ou les sauvegardes.

Ce PRX cible UNIQUEMENT l'exécutable **RDR2 PS4 1.00** confirmé par
l'utilisateur (SHA-256 de son EBOOT :
e3ae087f833b0f30f462bb7f880dd2955bf9f51dbb6e56706ee9bda81581feff).
Ne l'installe pas sur RDR2 PS4 1.32. Le firmware système de la PS5
(13.60) n'est pas la version du jeu.

La procédure suppose le **port communautaire etaHEN Unified**
pour PS5 13.60, avec chargement PRX de jeu par Title ID. Les anciennes
versions d'etaHEN ou d'autres jailbreaks n'ont pas nécessairement cette
fonction et peuvent utiliser d'autres chemins de configuration.
Source : https://github.com/GronedWaffel/etahen-11.00-13.60

## 1. Vérifier les informations sur la console

- RDR2 **édition PS4** installé, **version 1.00** (jeu sans mise à jour
  supérieure ; contrôler dans les informations du jeu).
- Trouver **l'identifiant CUSA réel** de cette installation. Selon les
  outils, il apparaît dans Toolbox (Display Title IDs), un gestionnaire
  de jeux PS4, ou les informations du package. Il commence par CUSA
  et cinq chiffres ; ne pas inventer de Title ID.
- Identifier la variante etaHEN démarrée sur la PS5. Le port Unified r1
  annonce game_plugins/TITLEID/ et le bouton Start qui arme les
  plugins **avant** le lancement du jeu.
- Sauvegarder les parties et désactiver les plugins expérimentaux
  susceptibles de modifier RDR2.

## 2. Préparer la copie sur le PC

Dans PowerShell, depuis la racine ps4_lml_bridge, après avoir remplacé
CUSA12345 par **le vrai Title ID** de RDR2 PS4 :

    python -B .\orbis\stage_pack_trace_100.py --title-id CUSA12345 --out .\ps5_install_100

CUSA12345 est UNIQUEMENT un exemple fictif, pas le Title ID de ton jeu.

Le script valide le format PS4 PRX (4f153d1d), le SHA-256 et le
rapport de compilation. Il refuse de remplacer un dossier déjà existant.
Il ne se connecte pas à la PS5.

Résultat :

    ps5_install_100/
      INSTALLATION_FR.md
      STAGING_MANIFEST.json
      data/etaHEN/game_plugins/CUSA12345/
        LmlBridge_RDR2_PS4_100_fiPackfile8_trace.prx

Ne copie **que** le fichier .prx : les deux fichiers .md/.json
servent à la documentation locale.

Si le PRX local a disparu, le reconstruire et tester par :

    powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\verify_pack_trace_100.ps1

## 3. Se connecter par FTP à la PS5

1. Fermer complètement RDR2.
2. Dans la PS5, charger **une seule** instance du jailbreak/etaHEN
   compatible. Ne pas superposer plusieurs versions d'etaHEN/kstuff.
3. Dans etaHEN Toolbox, activer **FTP** si nécessaire. Le FTP etaHEN
   utilise généralement le port **1337** ; le vérifier dans Toolbox.
4. Repérer l'adresse IP locale de la PS5 dans Paramètres > Réseau.
5. Depuis le PC, ouvrir FileZilla (ou autre client FTP), entrer cette
   adresse IP et le port 1337. Utiliser les paramètres d'authentification
   indiqués par le serveur actif. Ne pas exposer FTP sur Internet.

## 4. Copier UN fichier à l'endroit exact

Sur la PS5, avec FileZilla, aller dans :

    /data/etaHEN/game_plugins/<VRAI_CUSA>/

Créer le dossier du Title ID s'il n'existe pas, **sans effacer** les
plugins déjà installés. Copier seulement :

    LmlBridge_RDR2_PS4_100_fiPackfile8_trace.prx

Chemin final attendu :

    /data/etaHEN/game_plugins/<VRAI_CUSA>/LmlBridge_RDR2_PS4_100_fiPackfile8_trace.prx

Ne pas mettre ce PRX sous /data/etaHEN/plugins/ : c'est le répertoire
des plugins système, non celui des modules associés à RDR2 dans le
port Unified r1.

Ne copier ni EBOOT, ni vfs.asi, ni archives RPF8, ni ressources de mods.
Le PRX passif n'a pas besoin du fichier overlay.map.

## 5. Activer puis tester

1. RDR2 étant fermé, ouvrir Toolbox > Game Plugins (ou le menu de
   gestion des plugins de jeux présent dans la variante Unified).
2. Identifier le PRX de ce CUSA, sélectionner Start / armer le plugin
   AVANT le démarrage du jeu, si le gestionnaire le propose.
3. Lancer RDR2 en **mode Histoire hors ligne**.
4. Si le canal des journaux du noyau/chargeur est collecté, la ligne
   attendue est :

       [LML-100-TRACE] MODULE_ENTRY PS4-1.00; PASSIVE_NO_GAME_HOOK

   Ce message confirme seulement que module_start a exécuté du code ;
   il ne prouve aucun remplacement de fichiers. L'absence du message
   n'est PAS une preuve d'échec si sceKernelDebugOutText n'est pas
   capturé par la configuration du chargeur.
5. Fermer le jeu puis désarmer le plugin.

Le dossier de logs dépend de la variante d'etaHEN ; le port Unified
documente des diagnostics dans
/data/etaHEN/experimental-diagnostics/. Les erreurs de chargeur
peuvent ne pas s'afficher dans etaHEN.log. Un service Klog
(typiquement port 9081) peut être nécessaire pour capter les traces ;
ne pas supposer qu'il est activé.

## 6. Si cela échoue / désinstallation

- **RDR2 se bloque ou plante :** ne pas insister ; fermer le jeu,
  désarmer ce PRX dans Toolbox, supprimer UNIQUEMENT son fichier sous
  game_plugins/<VRAI_CUSA>/, puis relancer le jeu sans lui.
- **PRX invisible :** vérifier le CUSA, la variante etaHEN, la prise
  en charge des plugins de jeux et la correspondance des chemins.
- **Erreur arena mprotect ou PRX invalide :** possible problème
  du chargeur ou de mémoire. Un ticket public mentionne ce type d'erreur
  sur PS5 13.60 pour **RDR2 1.32 / CUSA08519**, pas un test établi
  de la version 1.00 :
  https://github.com/GronedWaffel/etahen-11.00-13.60/issues/8
- **Pas de mods visibles :** c'est le résultat normal. Ce PRX ne
  remplace encore aucun fichier de RDR2.

Ce projet ne contrôle pas la PS5 à distance. Ne considérer le
chargement réel comme réussi qu'avec une preuve observable.
Avant d'installer un hook actif, il faudra vérifier la base du module
chargé, la durée de vie des instances fiPackfile8 et toutes les
opérations sur les handles RAGE/RPF8.
