#!/usr/bin/env python3
"""Prepare a verified local FTP folder for the PASSIVE RDR2 PS4 v1.00 PRX.

This script does NOT contact the PS5, install a mod, or modify the game.
Only the matching community etaHEN Unified game_plugins layout is staged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRX = ROOT / "orbis_build" / "LmlBridge_RDR2_PS4_100_fiPackfile8_trace.prx"
REPORT = ROOT / "orbis_build" / "pack_trace_100_report.json"
TITLE_ID = re.compile(r"CUSA[0-9]{5}\Z", re.ASCII)
SELF_MAGIC = bytes.fromhex("4f153d1d")
EXPECTED_EBOOT_SHA = (
    "e3ae087f833b0f30f462bb7f880dd2955bf9f51dbb6e56706ee9bda81581feff"
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stage(
    title_id: str, output: Path, *,
    source_prx: Path = PRX, report_path: Path = REPORT,
) -> dict:
    if not isinstance(title_id, str) or TITLE_ID.fullmatch(title_id) is None:
        raise ValueError("Le Title ID doit etre CUSA suivi de cinq chiffres.")
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError("Le dossier de destination existe deja ; aucun ecrasement.")
    if not source_prx.is_file() or not report_path.is_file():
        raise ValueError("PRX ou rapport manquant : recompiler le module 1.00.")

    blob = source_prx.read_bytes()
    if len(blob) < 128 or blob[:4] != SELF_MAGIC:
        raise ValueError("Le module n'est pas un SELF/PRX Orbis valide.")
    report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    if (
        report.get("artifact") != PRX.name
        or report.get("profile_game") != "RDR2 PS4 1.00"
        or report.get("profile_source_eboot_sha256") != EXPECTED_EBOOT_SHA
        or report.get("sha256") != sha256(blob)
        or report.get("bytes") != len(blob)
        or report.get("auto_installed_in_game") is not False
        or report.get("console_tested") is not False
        or report.get("direct_resource_replacement_available") is not False
        or report.get("host_only_fixture_not_exported") is not True
        or report.get("version_1_32_rejected_before_memory_read") is not True
    ):
        raise ValueError("Le rapport de build ou le checksum PRX est incompatible.")

    game_path = f"/data/etaHEN/game_plugins/{title_id}/{PRX.name}"
    manifest = {
        "format": "rdr2-ps4-100-passive-ftp-stage/1",
        "title_id_to_verify_on_console": title_id,
        "game_patch_required": "1.00",
        "system_firmware": "PS5 13.60",
        "loader_required": "etaHEN Unified fork supporting game_plugins/<TITLEID>/ PRX",
        "console_file": game_path,
        "sha256": sha256(blob),
        "bytes": len(blob),
        "original_eboot_included": False,
        "game_files_modified": False,
        "console_transfer_performed": False,
        "automatic_game_hook": False,
        "in_game_mod_replacement": False,
        "console_tested": False,
        "expected_debug_message":
            "[LML-100-TRACE] MODULE_ENTRY PS4-1.00; PASSIVE_NO_GAME_HOOK",
    }
    notes = f"""# Installation PRX de diagnostic — RDR2 PS4 1.00

## Ce que tu installes

Le module est une SONDE PASSIVE, pas un modloader fonctionnel.
Il ne remplace aucun fichier RPF8, ne contient aucun mod, et ne pose
aucun hook au demarrage. La version 1.32 n'est PAS compatible.

Title ID selectionne : {title_id}
Tu dois confirmer ce meme identifiant sur TA console.
Tu dois aussi confirmer la version de RDR2 PS4 : 1.00.

## Procedure pour etaHEN Unified compatible sur PS5 13.60

1. Ferme RDR2 completement. Fais une sauvegarde de tes parties.
2. Active uniquement une instance d'etaHEN compatible et son FTP.
   Sur la plupart des etaHEN : FTP port 1337 (a verifier sur ta console).
3. Dans FileZilla, connecte-toi en FTP a l'adresse IP locale de ta PS5,
   port 1337. Le PC et la PS5 doivent etre sur le meme reseau.
4. Copie UNIQUEMENT le PRX contenu dans le sous-dossier data de ce kit
   vers le chemin EXACT sur la console :
   {game_path}
   Cree le dossier CUSA si necessaire ; ne remplace aucun autre module.
   NE copie PAS INSTALLATION_FR.md ni STAGING_MANIFEST.json sur la PS5.
5. Si ton etaHEN possede Game Plugins, selectionne ce PRX et fais
   Start / Arm AVANT de lancer RDR2. N'active aucun autre PRX d'essai.
6. Lance RDR2 PS4 1.00, mode Histoire, HORS LIGNE.
   Pas de menu ou de mods visibles attendus. Un collecteur de traces
   noyau peut montrer :
   [LML-100-TRACE] MODULE_ENTRY PS4-1.00; PASSIVE_NO_GAME_HOOK
   L'absence de ce message ne prouve PAS que le PRX n'a pas tourne.
7. Ferme le jeu. Dans etaHEN, desarme ce PRX avant de le retirer.
   Supprime UNIQUEMENT :
   {game_path}

## En cas d'erreur

- Blocage / crash au lancement : retire le PRX, ferme RDR2 et relance
  sans le plugin. Ne modifie pas les fichiers du jeu.
- Plugin absent dans Toolbox : ton etaHEN ne gere peut-etre pas ce
  format ou ce dossier. Ne deplace pas le PRX vers les plugins systeme.
- Erreur mprotect / arena : probleme potentiel de chargeur ou de
  protections memoire ; une compilation PRX valide ne garantit pas
  la compatibilite de son chargement dans RDR2.
- Pas de logs : sceKernelDebugOutText peut necessiter un service Klog
  ou un collecteur ; ne modifie pas l'EBOOT pour obtenir des logs.

Le script d'origine ne communique pas avec la console. Les sources et
l'etat exact sont dans orbis/RDR2_PS4_100_TRACE_STATUS.md du depot.
"""
    payloads = {
        f"data/etaHEN/game_plugins/{title_id}/{PRX.name}": blob,
        "INSTALLATION_FR.md": notes.encode("utf-8"),
        "STAGING_MANIFEST.json": (
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8"),
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="rdr2-100-ftp-stage-", dir=output.parent))
    try:
        for relative, data in payloads.items():
            dest = temp.joinpath(*relative.split("/"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        for relative, expected in payloads.items():
            if sha256(temp.joinpath(*relative.split("/")).read_bytes()) != sha256(expected):
                raise RuntimeError(f"La copie locale est alteree : {relative}")
        temp.rename(output)
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return {
        "folder": str(output.resolve()),
        "console_path": game_path,
        "sha256": sha256(blob),
        "bytes": len(blob),
        "files": len(payloads),
        "console_transfer_performed": False,
        "in_game_mod_replacement": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title-id", required=True,
                        help="ID REEL de RDR2 PS4 sur la console, ex. CUSA12345")
    parser.add_argument("--out", type=Path, required=True,
                        help="Nouveau dossier local, qui ne doit pas deja exister")
    args = parser.parse_args()
    try:
        print(json.dumps(stage(args.title_id, args.out), indent=2, ensure_ascii=False))
        return 0
    except (ValueError, OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"Preparation impossible : {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
