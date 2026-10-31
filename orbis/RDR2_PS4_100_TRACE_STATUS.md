# RDR2 PS4 1.00 — fiPackfile8 hook, solidité et limites

**Priorité actuelle : RDR2 PS4 1.00. La version 1.32 constitue une cible
distincte.** Ce document décrit uniquement des composants indépendants ;
il ne contient ni jeu, ni EBOOT, ni binaire propriétaire LML.

## Avertissement critique : test PS5 LIVE effectué le 31 octobre 2026

La PS5 **13.40**, avec Y2JB/Kstuff Lite et ps5debug-NG, a identifié
le jeu réellement lancé : **RDR2 PS4 CUSA08519 v01.00**. Le
profil fiPackfile8 de CET ancien EBOOT n'a **pas correspondu**
au vrai processus : RTTI, vtable et quatre préfixes de code différents,
avec des données mémoire réelles non nulles. **Ne pas armer le
hook `rdr2_100_pack_trace_attach_checked` sur cette console.**
Ce PRX compilé est seulement un devkit hors-jeu ; aucun chargement
dans le jeu n'a été testé. Voir
`orbis/PS5DEBUG_NG_RDR2_100_LIVE_STATUS.md`.

## Identité de la version

L'EBOOT analysé, déclaré par son propriétaire comme **RDR2 PS4 1.00**,
a pour SHA-256 :
e3ae087f833b0f30f462bb7f880dd2955bf9f51dbb6e56706ee9bda81581feff

Classes et méthodes observées directement dans ce fichier :

| Élément | RVA / valeur |
| --- | --- |
| fiPackfile8 vtable | 0x066B00F8 |
| Nombre de slots contigus | 112 |
| FNV-1a 64 bits des 112 RVA de méthodes | 8eaecb696678dad0 |
| Méthode Open / slot 2 | 0x0452A480 |
| Méthode OpenBulk candidate / slot 6 | 0x0452A780 |
| Méthode Read candidate / slot 13 | 0x0452B9D0 |
| Méthode ReadBulk candidate / slot 14 | 0x0452BA60 |
| Méthode Close / slot 19 | 0x0452BE00 |
| Registre d'instances candidat | 0x08053D40 |

Les signatures de cet EBOOT ne sont PAS celles de la version 1.32.
Le Title ID de l'EBOOT FICHIER analysé reste inconnu ; en revanche,
le vrai jeu sur console annonce CUSA08519/01.00 et ne correspond
pas au profil, malgré ce numéro de patch.

## Ce qui est compilé

- runtime/rdr2_100_pack_trace.h et .cpp : interception de slot 2 sur
  UN SEUL objet fiPackfile8 vivant. Copie privée de 112 méthodes et
  de l'en-tête RTTI Itanium, échange atomique d'un seul vptr d'objet.
  La fonction originale Open est appelée exactement une fois.
- runtime/rdr2_100_registry.h et .c : inspection en lecture seule du
  registre candidat (par lots de 4096 entrées maximum) avec validation
  de vptr, index d'objet et des adresses par callback.
- runtime/rage_eboot_profile.c : validation de la chaîne RTTI, de
  six pointeurs virtuels et des premiers octets de quatre fonctions.
- rdr2_100_pack_preflight : valide ensuite la limite des 112 slots,
  l'offset-to-top Itanium, les 112 pointeurs de méthodes normalisés
  par la base du processus et leur empreinte FNV.
- orbis/pack_trace_100_module.c et build_pack_trace_100.ps1 :
  PRX Orbis autonome avec module_start/module_stop et 13 exports.
- tools/verify_eboot_100.py : comparaison de l'EBOOT original fourni
  à son SHA-256, sa table et son empreinte complète ; lecture seule.
- tools/verify_pack_trace_100.ps1 : compilation hôte, PRX,
  contrôles des exports, tests et rapport final.

Module Windows/PS4 local obtenu :
orbis_build/LmlBridge_RDR2_PS4_100_fiPackfile8_trace.prx

Les binaires compilés sont ignorés par Git. Le dépôt public conserve
les scripts et sources permettant de les reconstruire, ainsi que
des rapports de validation ne contenant aucune donnée du jeu.

## Protections intégrées

1. **Vérification obligatoire de version.** PS4 1.32 est refusée avant
   tout accès mémoire ; seule 1.00 est acceptée.
2. **Fingerprint intégral des 112 méthodes.** Les quatre préfixes de
   code, RTTI, pointeurs et les limites de la vtable sont validés.
3. **Pas de patch de code.** La version de trace ne touche ni aux
   pages exécutables, ni à la vtable globale du jeu, ni aux RPF8.
4. **Échange atomique conditionnel.** Si le vptr a changé entre
   l'inspection et l'installation, l'opération est annulée.
5. **Concurrence.** Le compteur d'appels actifs interdit un retrait
   lorsque Open est en cours. Le callback de télémétrie ne peut pas
   provoquer de récursion concurrente dans la journalisation.
6. **Exceptions.** Le compteur d'appels est décrémenté même si
   la fonction Open originale lève une exception. Les exceptions
   provenant du callback de journalisation sont absorbées.
7. **Shadow vtable jamais réutilisée.** Après le retrait, un ancien
   pointeur virtuel gardé par un thread appelle toujours Open original.
   Il est interdit de réarmer une autre instance dans ce PRX ;
   redémarrer le processus pour repartir à zéro.
8. **Ne pas décharger le PRX après une activation.** Un pointeur
   vers la fonction de trace peut encore être en cache sur un thread.
   Le module_stop retourne une erreur et journalise REFUSE_UNLOAD_AFTER_ATTACH.
   Certains chargeurs peuvent ignorer ce code : ne pas leur confier
   la gestion de ce scénario sans validation.
9. **Aucune allocation ni I/O dans la fonction de hook.** Le callback
   fourni par le chargeur doit rester borné, synchrone et non bloquant.
10. **Pas de faux handles.** Le Open original fournit le handle RAGE
    réel. La redirection de fichiers du pont LML est volontairement
    désactivée tant que Read/Close/Seek/Size/etc. ne sont pas branchés.

## Conditions supplémentaires impératives avant de brancher au jeu

La fonction rdr2_100_pack_trace_attach_checked prend deux readers
indépendants : un lecteur d'adresses RVA validé et un lecteur d'adresses
absolues validé. Les callbacks doivent refuser les zones non mappées.
Ils ne donnent aucun droit de patcher une adresse arbitraire.

Le chargeur doit fournir **l'adresse de base réelle du module RDR2**
(ASLR), la version exacte **1.00**, un objet vivant **fiPackfile8**,
et immobiliser son cycle de vie pour éviter une destruction pendant
l'inspection et l'échange du vptr. Ces préconditions ne sont pas
encore démontrées sur ta PS5.

Le registre à 0x08053D40 est une piste issue du destructeur,
**pas** une API de recherche validée sur console : ne pas scanner
toutes les entrées par défaut pendant une frame de jeu.

Le module démarre en **PASSIVE_NO_GAME_HOOK**. Aucun appel automatique
à attach_checked n'est effectué. Ce choix évite un crash si le
chargeur PS5 ou l'environnement mémoire diffère.

### Tester le PRX en mode passif

1. Vérifier le vrai CUSA et que RDR2 PS4 est en **1.00**, pas 1.32.
2. Utiliser exclusivement un chargeur supportant les plugins PS4,
   et désactiver les autres modules expérimentaux.
3. Exécuter le mode Histoire hors ligne ; consulter la sortie du
   chargeur/du noyau si disponible.
4. Message attendu (si le canal debug est collecté) :
   [LML-100-TRACE] MODULE_ENTRY PS4-1.00; PASSIVE_NO_GAME_HOOK
5. Arrêter RDR2 et retirer le plugin pour revenir à l'état initial.

Aucun résultat de test réel de la PS5 n'est enregistré dans le projet.

## Vérifier et reconstruire sur Windows

Depuis la racine de ps4_lml_bridge :

    powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\verify_pack_trace_100.ps1

Le programme Windows de test synthétique exécute notamment 4 threads
et plus de 500 ouvertures ; il valide les signatures attendues, des
signatures modifiées, le refus 1.32 sans lecture, le refus d'un
détachement pendant un appel actif, l'invocation de la méthode d'origine,
les exceptions et les pointeurs virtuels conservés après détachement.

Le PRX Orbis a été compilé et ses exports/SELF sont vérifiés.
**Ce n'est PAS une preuve que le hook est déjà actif sur PS5.**

## Étape suivante pour un modloader véritablement fonctionnel

1. D'abord valider que le PRX passif est chargé par le processus RDR2 1.00.
2. Déterminer une interface de lecture sûre de l'image en mémoire et
   vérifier la durée de vie des objets du registre.
3. Armer le hook Open en observation sur UN seul objet, sous verrou
   du moteur, puis mesurer les appels réellement observés.
4. Analyser les ABI des méthodes Read, Seek, Close, OpenBulk, taille,
   métadonnées et la gestion des chemins relatif/absolu.
5. Intégrer la résolution des chemins LML et les remplacements par
   token uniquement après interception complète et cohérente des
   opérations sur ces tokens. Tester un remplacement non critique.
6. Les ressources XML RAGE/PSO, Stream et Data nécessitent encore
   sérialisation et/ou enregistrement auprès du moteur.

## Référence publique externe

La preuve de concept WildRAGE-s vise également le PS4 1.00 et une
redirection plus restreinte XML/OMT/DAT :
https://github.com/rfoodxmodz/RDR2-WildRAGE-s

L'intégration du projet actuel est indépendante : aucun code ni
binaire tiers n'est copié depuis ce dépôt.
