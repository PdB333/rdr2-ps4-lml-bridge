#!/usr/bin/env python3
"""Stage a read-only PS4 PRX test layout for a user-selected RDR2 Title ID.

No network operations, no console access, no game binary modifications.
Only compatible etaHEN forks honor the staged game_plugins/ path.
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
SOURCE_PRX = ROOT / "orbis_build" / "LmlBridge_132_readonly_diagnostic.prx"
BUILD_REPORT = ROOT / "orbis_build" / "readonly_diag_report.json"
RUNTIME_PRX = ROOT / "orbis_build" / "LmlBridge_132_runtime_probe.prx"
RUNTIME_REPORT = ROOT / "orbis_build" / "runtime_probe_report.json"
DEFAULT_MAP = ROOT / "orbis" / "probe_data" / "overlay.map"
TITLE_ID = re.compile(r"^CUSA[0-9]{5}$")
MAGIC = bytes.fromhex("4f153d1d")


def sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def stage(title_id: str, output: Path, mode: str = "diagnostic") -> dict:
    if mode not in ("diagnostic", "runtime"):
        raise ValueError("Mode must be diagnostic or runtime")
    if not TITLE_ID.fullmatch(title_id):
        raise ValueError("Title ID must be CUSA followed by exactly five digits")
    if output.exists() or output.is_symlink():
        raise ValueError(f"Output directory already exists: {output}")
    source_prx = SOURCE_PRX if mode == "diagnostic" else RUNTIME_PRX
    build_report = BUILD_REPORT if mode == "diagnostic" else RUNTIME_REPORT
    if not source_prx.is_file() or not build_report.is_file():
        raise ValueError(f"Build the Orbis {mode} PRX first")

    original = source_prx.read_bytes()
    build = json.loads(build_report.read_text(encoding="utf-8-sig"))
    if original[:4] != MAGIC or sha256(original) != build["sha256"]:
        raise ValueError("PRX contents do not match the verified build report")
    hook_key = "has_RAGE_file_hooks" if mode == "diagnostic" else "hooks_RAGE_RPF"
    test_key = "console_tested" if mode == "diagnostic" else "tested_on_console"
    if build.get(hook_key) is not False or build.get(test_key) is not False:
        raise ValueError("Build report unexpectedly claims live game support")
    overlay = DEFAULT_MAP.read_bytes()
    if not overlay.startswith(b"LML_OVERLAY_V1\n") or not overlay.endswith(b"\n"):
        raise ValueError("The empty diagnostic map has an invalid magic/version")

    layout = {
        f"data/etaHEN/game_plugins/{title_id}/{source_prx.name}": original,
        "data/etaHEN/lml_bridge/overlay.map": overlay,
    }
    manifest = {
        "format": "rdr2-ps4-readonly-probe-stage/2",
        "mode": mode,
        "title_id": title_id,
        "game": "Red Dead Redemption 2 PS4 1.32",
        "ps5_firmware": "13.60",
        "loader": "Only etaHEN variants with game_plugins/<TITLEID>/ PRX support",
        "purpose": ("Test PRX entrypoint and kernel logging" if mode == "diagnostic" else
                    "Test C++ runtime and independent LML overlay map loading"),
        "game_data_modified": False,
        "game_memory_patched": False,
        "tested_on_console": False,
        "rpf_vfs_hook_available": False,
        "expected_logs": (
            ["[LML-ORBI-DIAG] MODULE_ENTRY RDR2-PS4-1.32 PS5-13.60",
             "[LML-ORBI-DIAG] MAP_OK R=0 S=0 D=0"]
            if mode == "diagnostic" else
            ["[LML-ORBI-RUNTIME] MODULE_ENTRY RDR2-PS4-1.32",
             "[LML-ORBI-RUNTIME] MAP_LOADED R=0 S=0 D=0"]
        ),
        "other_possible_log": (
            "[LML-ORBI-DIAG] MAP_UNAVAILABLE R=0 S=0 D=0"
            if mode == "diagnostic" else
            "[LML-ORBI-RUNTIME] MAP_UNAVAILABLE_OR_INVALID"
        ),
        "files": [
            {"console_path": "/" + name, "bytes": len(data), "sha256": sha256(data)}
            for name, data in sorted(layout.items())
        ],
    }
    instructions = f"""# RDR2 PS4 1.32 - Test de chargement PRX (PS5 13.60)

Fichiers prepares pour {title_id}. Mode selectionne: {mode}. Ne pas copier si ce Title ID ne correspond pas au jeu.

Ce test suppose le port communautaire etaHEN avec un chargeur de plugins
de jeux PS4. Le firmware 13.60 seul ne suffit pas. Un echec arena mprotect
sur RDR2 1.32 / CUSA08519 a ete rapporte le 25 octobre 2026 :
https://github.com/GronedWaffel/etahen-11.00-13.60/issues/8

## Procedure reversible, hors ligne

1. Verifier le Title ID exact du jeu dans son gestionnaire. Ne pas
   utiliser {title_id} si ce n'est pas celui de RDR2 installe.
2. Sauvegarder les plugins existants, puis copier les deux fichiers du
   dossier data du paquet vers les memes chemins sur la console :
     /data/etaHEN/game_plugins/{title_id}/{source_prx.name}
     /data/etaHEN/lml_bridge/overlay.map
   Ne pas ecraser les autres modules.
3. Dans etaHEN Game Plugins, armer uniquement ce PRX AVANT
   d'ouvrir le jeu, si cette fonctionnalite est presente.
4. Lancer RDR2 en mode Histoire, HORS LIGNE, et examiner les logs du
   chargeur et le canal sceKernelDebugOutText. Le PRX ne produit pas
   de notification graphique, et les messages noyau ne sont pas
   forcement enregistres dans etaHEN.log.

## Interpretation des resultats

- MODULE_ENTRY : le chargeur a execute une entree du module.
- MAP_OK R=0 S=0 D=0 : le module a lu la map vide du test.
- MAP_UNAVAILABLE : module execute, mais map absente/inaccessible depuis
  le sandbox du processus.
- MAP_BAD_HEADER / MAP_BAD_RECORD / MAP_LIMIT : map invalide.
- Erreur arena mprotect avant MODULE_ENTRY : blocage du chargeur ou des
  permissions memoire. Voir issue #8.
- Aucun log : le canal debug peut ne pas etre capture. Il est
  incorrect de conclure automatiquement que le module a echoue.

Desactiver ensuite la sonde, fermer le jeu et supprimer seulement les
fichiers de test. Ne pas modifier les autres dossiers etaHEN.

Mode runtime: utiliser UNIQUEMENT apres un test diagnostic reussi.
Le runtime C++ utilise des bibliotheques de plus que la sonde C minimale.
Ne PAS charger les deux modules dans le jeu en meme temps.

Ce module ne redirige PAS les ressources RAGE/RPF et n'est PAS une
conversion complete de Lennys Mod Loader.
"""
    layout["PROBE_MANIFEST.json"] = (
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    layout["INSTALLATION_TEST.md"] = instructions.encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="lml-probe-stage-", dir=output.parent))
    try:
        for relative, data in layout.items():
            dst = tmp.joinpath(*relative.split("/"))
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
        for relative, data in layout.items():
            copied = tmp.joinpath(*relative.split("/")).read_bytes()
            if sha256(copied) != sha256(data):
                raise RuntimeError(f"Staging hash mismatch: {relative}")
        tmp.rename(output)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return {
        "path": str(output.resolve()),
        "title_id": title_id,
        "mode": mode,
        "files": len(layout),
        "prx_sha256": sha256(original),
        "testing_only": True,
        "console_transfer_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title-id", required=True, help="Exact RDR2 PS4 Title ID (CUSAxxxxx)")
    parser.add_argument("--out", type=Path, required=True, help="New staging directory")
    parser.add_argument("--mode", choices=("diagnostic", "runtime"), default="diagnostic")
    args = parser.parse_args()
    try:
        result = stage(args.title_id, args.out.resolve(), mode=args.mode)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Unable to prepare console staging: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
