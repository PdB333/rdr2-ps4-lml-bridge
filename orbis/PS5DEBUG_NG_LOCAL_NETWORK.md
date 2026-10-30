# Connexion locale PS5 13.40 : Y2JB / Kstuff Lite / ps5debug-NG

## Objectif

Pouvoir dialoguer depuis le PC Windows deja connecte au projet avec
**ps5debug-NG 1.3.2** sur PS5, via reseau local ou Tailscale. La sonde
verifie que le firmware annonce est **13.40** (console confirmee par son proprietaire) et refuse de poursuivre sinon.
Aucune connexion ChatGPT -> console directe et aucun port Internet a ouvrir.
La sonde teste la connexion et le firmware : elle ne change ni les
processus, ni la memoire ni les fichiers RDR2.

## A. Sur la PS5

1. Mettre PC et PS5 sur le meme routeur et reseau local. Eviter le
   reseau invite ou la fonction d'isolation des clients Wi-Fi.
2. Lancer Y2JB / Kstuff Lite comme d'habitude. Ne pas superposer etaHEN.
3. Dans le Payload Manager deja present, choisir le fichier officiel
   **ps5debug-NG.elf** de la release **v1.3.2** :

   https://github.com/Pharaoh2k/ps5debug-NG/releases

   Le projet exige un chargeur ELF PS5 compatible umtx. Certains Y2JB
   Payload Managers chargent des ELF, mais on doit verifier que CETTE
   configuration accepte ce payload. En cas de message d'echec, stopper.
4. Attendre une notification de chargement ps5debug-NG et la version FW
   affichee. Le serveur devrait alors ecouter en **TCP port 744**.
5. Optionnel : relever l'IP dans Parametres > Reseau > Etat de la
   connexion > Afficher l'etat de la connexion > Adresse IP.

## B. Sur le PC Windows

Ouvrir PowerShell a la racine du depot ps4_lml_bridge :

    python -B .\tools\ps5debug_ng_probe.py --discover

La commande envoie **une seule** requete de decouverte UDP port 1010 ;
si elle identifie exactement une console, elle interroge deux commandes
de version TCP port 744. Si le broadcast est bloque, saisir l'adresse
locale affichee par la PS5 :

    python -B .\tools\ps5debug_ng_probe.py --ip 192.168.1.123

192.168.1.123 est un exemple fictif. NE PAS l'utiliser a moins que
les parametres de la PS5 affichent exactement cette adresse.

## B bis. Adresse Tailscale (100.64.0.0/10)

Une adresse qui commence par 100.x.x.x peut relever de l'espace CGNAT
utilise par Tailscale : elle n'est PAS une adresse IPv4 LAN classique.
Pour un appareil deja present dans le meme tailnet que ce PC Windows,
utiliser explicitement :

    python -B .\tools\ps5debug_ng_probe.py --ip VOTRE_ADRESSE_TAILSCALE --tailscale

Ne pas mettre le texte VOTRE_ADRESSE_TAILSCALE tel quel : le remplacer
par l'adresse affichee sur ton propre Tailscale.

Le drapeau --tailscale ne permet QUE 100.64.0.0/10 ET exige que la
route vers cette adresse utilise une interface Windows nommee
Tailscale avant tout appel TCP. Il refuse une route Ethernet/Internet
classique, meme si l'adresse est en 100.x. La decouverte UDP --discover
n'est pas disponible dans cette configuration : il faut --ip.

Un message d'ecart de firmware est bloquant pour la suite :
identifier l'appareil dans Tailscale ET verifier la version affichee
dans Parametres PS5 > Systeme > Logiciel systeme > Informations de
la console. Ne pas utiliser des offsets RDR2 ou firmware sur un appareil
dont la version n'est pas celle attendue.

Resultat attendu sur FW 13.40 :

    {
      "service": "ps5debug-NG by OSR v1.3.2 ...",
      "firmware": "13.40",
      "expected_firmware": "13.40",
      "firmware_matches_expected": true,
      "read_only_identity_test": true,
      "debug_attached": false,
      "game_memory_accessed": false,
      "plugin_injected": false
    }

L'adresse IP de la console est affichee localement mais ne sera pas
enregistree dans un fichier Git. Le script refuse les IP publiques,
les mauvaises signatures et un firmware different.

## C. Si cela echoue

- Rien trouve : charger ps5debug-NG d'abord, puis essayer avec --ip.
- Connection refused TCP 744 : serveur non charge ou chargeur incompatible.
- Timeout : reseaux separes, firewall, Wi-Fi invite ou isolation client.
- Plusieurs consoles reconnues : utiliser --ip avec l'adresse de SA PS5.
- Firmware different de 13.40 : le serveur debug repond, mais cela
  peut etre une autre console Tailscale ou une version differente.
  Verifier l'appareil et sa version sur l'ecran PS5 avant toute lecture
  de processus ou modification memoire.
- Aucun affichage : consulter les notifications du gestionnaire Y2JB.

**Ne pas ouvrir TCP 744 sur Internet, ne pas modifier la box pour faire
du port forwarding.** Sur Tailscale, limiter l'acces au tailnet du
proprietaire et ne pas exposer ps5debug-NG a des appareils inconnus. ps5debug-NG comporte par ailleurs des operations
d'ecriture de memoire/noyau. Notre script n'envoie que les commandes
non destructives BRANDING et FW_VERSION.

## D. Note d'implementation et source

Le code ps5debug-NG v1.3.2 dans debugger/source/meta.c etablit que
CMD_BRANDING (0xBD000501) renvoie directement un uint32 longueur puis
les octets, sans mot de statut. CMD_FW_VERSION (0xBD000500) renvoie un
uint16 decimal (1340 pour 13.40), lui aussi sans mot de statut.
Le script n'autorise aucune autre commande.

Le serveur du proprietaire a deja renvoye **ps5debug-NG v1.3.2** et
**13.40** via Tailscale. La correspondance avec sa console a ete
confirmee par l'utilisateur ; aucun jeu n'etait lance et aucune
operation de lecture de processus, memoire ou injection n'a ete faite.
Le script permet aussi de choisir une autre valeur attendue
avec --expected-fw XX.YY, pour de futurs essais ; le defaut reste 13.40.

Il restera a valider sur console l'inspection RDR2 1.00, puis la
possibilite de charger le PRX passif dans son processus. La disponibilite
du serveur debug TCP 744 ne demontre pas un modloader fonctionnel.

Sources :
https://github.com/Pharaoh2k/ps5debug-NG
https://github.com/Pharaoh2k/ps5debug-NG/blob/master/PROTOCOL.md
https://github.com/Vampitech/ps5-y2jb-autoloader
