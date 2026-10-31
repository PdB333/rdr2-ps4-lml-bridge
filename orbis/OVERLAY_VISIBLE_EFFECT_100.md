# Overlay à effet visible — RDR2 PS4 1.00 (voie hors-ligne sûre)

But : documenter la **seule** voie de remplacement de ressource sûre hors-ligne
pour le mode Histoire 1.00, de bout en bout, sans repack RPF8/RSC8 et sans
toucher la mémoire du jeu avant validation de signatures.

Profil cible : EBOOT RDR2 PS4 1.00, Title ID CUSA08519,
SHA-256 `e3ae087f833b0f30f462bb7f880dd2955bf9f51dbb6e56706ee9bda81581feff`.
PS5 FW 13.40 jailbreaké (Y2JB + Kstuff Lite + ShadowMountPlus, Payload Manager,
ps5debug-NG v1.3.2, **sans etaHEN**).

## Pourquoi seul le texte/XML/.meta est sûr hors-ligne

Le backend VFS (`lml_rage_*`, cf. `runtime/rage_vfs_redirect.h`) détourne la
lecture d'un fichier au niveau du **lecteur de texte** de RAGE
(`lml_rage_select_loader_path`). À cette frontière, une ressource texte/XML/.meta
chargée en clair peut être remplacée octet pour octet par un payload de même
nature : le moteur la reparse normalement, sans étape de sérialisation binaire.

Les ressources binaires RPF8/RSC8 (modèles, textures, archives) exigent une
sérialisation/repack par le moteur ; tant que cet outillage n'existe pas, les
remplacer hors-ligne corromprait le chargement. Elles sont donc **hors périmètre**
de cette voie. Règle respectée : préserver le fonctionnement original de RDR2.

## Chaîne de bout en bout (vérifiée sur PC, hors console)

```
install.xml  --(compiler.py)-->  overlay.map + payload/  --(OverlayIndex)-->  résolution de clé
```

1. **Mod source** : un `install.xml` `EasyInstall` avec un `FileReplacement`
   `<GamePath>` (clé ressource `archive:/chemin`) + `<FilePath>` (payload local).
2. **Compilation** : `python compiler.py --source <dossier> --out <stage>`
   produit `overlay.map` (en-tête `LML_OVERLAY_V1`, lignes
   `kind⇥clé⇥payload-relatif⇥sha256⇥octets`), l'arbre `payload/` et `catalog.json`.
3. **Chargement runtime** : `OverlayIndex::load` (`runtime/overlay_index.cpp`)
   parse la carte, **valide sha256 (64 hex) et taille** contre le payload
   physique, et sert les lookups (clé insensible à la casse ; miss = `NOT_FOUND`).

Exemple clean-room fourni : `examples/overlay_hello_100/` (un `.meta` XML
synthétique, **aucun octet du jeu**), marqueur `LML_OVERLAY_HELLO_100`.
Test de la chaîne : `tests/test_overlay_hello_100.py` (compile + charge via
`runtime/overlay_probe.exe`, skip si le probe n'est pas bâti).

## Racine du payload sur console

Pour la configuration **sans etaHEN** en FW 13.40, la racine des payloads est :

```
/data/lml_bridge/
```

(cohérent avec `VALID_PATH_PREFIXES` de `inject.py`). Les valeurs par défaut C
de certains modules pointent encore vers l'ancien `/data/etaHEN/lml_bridge` :
elles sont **surchargables au build** (`-D...`) et ne doivent pas être utilisées
telles quelles pour ce setup.

## Ce qui reste non vérifié (console uniquement)

- L'armement du redirect VFS côté console (le détour `fiPackfile8` est outillé
  et testé hors-ligne — `runtime/rdr2_100_detour.*` — mais jamais appliqué sur
  cible ; cf. [PRX_LOADING_STUDY_100](PRX_LOADING_STUDY_100.md)).
- La preuve d'un effet **réellement visible** en jeu : exige une ressource .meta
  réelle, vérifiée 1.00 (le payload d'exemple est synthétique) et le mount du
  bridge sur la PS5 (actuellement hors ligne, jailbreak perdu au reboot).
- L'invocation de natives (`runtime/rdr2_100_natives.*`) reste refusée tant que
  l'ABI du `NativeContext` n'est pas validée
  (cf. [NATIVE_DISPATCH_STUDY_100](NATIVE_DISPATCH_STUDY_100.md)).

Tant que ces points ne sont pas validés sur console, aucun test simulé ne vaut
réussite d'un modloader sur machine réelle.
