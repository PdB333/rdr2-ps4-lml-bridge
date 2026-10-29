# Project handoff for coding agents

## Goal and status

Build an independent LML-style file replacement bridge for Red Dead
Redemption 2, **PS4 title update 1.32**, running as a PS4 game on a
**PS5 firmware 13.60 jailbreak**. Focus on offline story mode.

The source and Orbis PRX compile successfully. This is **NOT a functioning
in-game modloader yet**. The RAGE/RPF8 read-through replacement and XML/text
loader callback are tested against a simulated original RAGE VFS only.
Version-specific interception of RDR2 PS4 1.32 has NOT been installed.
The exported lml_rage_game_hook_installed() currently returns 0.

Do not report simulated success as a successful in-game hook.

## Primary files

- runtime/rage_vfs_redirect.h and .cpp: C bridge for open/read/read_at/seek,
  size/close/stat and passthrough to the original VFS. Also includes
  lml_rage_select_loader_path and lml_rage_dispatch_text_loader for
  XML/META/OMT/DAT loaders.
- runtime/overlay_index.hpp and .cpp: overlay.map parser/index.
- compiler.py: install.xml LML manifest and asset staging generator.
- orbis/rage_vfs_module.c + orbis/build_rage_vfs.ps1: the Orbis PRX target,
  with NO game hook currently installed.
- orbis/loader_diag_module.c + orbis/build_readonly_diag.ps1: minimal
  read-only entrypoint and loader probe.
- orbis/bridge_runtime_module.c + orbis/build_runtime_probe.ps1:
  C++ runtime initialization probe.
- runtime/rage_vfs_harness.cpp and tests/test_rage_vfs.py:
  simulated game VFS, MODDED_CONTENT vs ORIGINAL_CONTENT.
- orbis/RAGE_VFS_132_PORT.md, orbis/CONSOLE_DIAGNOSTIC.md and
  PORTING_STATUS.md: detailed analysis, console test protocol, limitations.

## Local Windows environment

Existing project working directory:
Use a local checkout of this repository as your working directory.

OpenOrbis v0.5.4 SDK and LLVM 18.1.8 are installed locally and ignored
by Git under .toolchains/. They are NOT in this repository.
The Windows build scripts expect them and Strawberry g++.
Compiled PRX files are kept locally and are intentionally excluded from Git,
because build products can embed host filesystem paths.

Build in PowerShell from the repository root:
    powershell -NoProfile -ExecutionPolicy Bypass -File .\orbis\build_rage_vfs.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File .\orbis\build_readonly_diag.ps1
    powershell -NoProfile -ExecutionPolicy Bypass -File .\orbis\build_runtime_probe.ps1

Build the native RAGE VFS host test harness:
    g++ -std=c++17 -O2 -Wall -Wextra -Werror -static -static-libgcc -static-libstdc++ .\runtime\overlay_index.cpp .\runtime\rage_vfs_redirect.cpp .\runtime\rage_vfs_harness.cpp -o .\orbis_build\rage_vfs_harness.exe

Full tests AFTER generating build outputs:
    python -B -m unittest discover -s .\tests -p "test_*.py" -v

The previous Windows working directory passed 42 offline tests. A fresh
clone needs the locally installed SDK and generated host test executables
for full test coverage; missing build outputs can cause skips or errors.

## Remaining tasks

1. Identify the actual RDR2 PS4 1.32 eboot.bin/ELF and Title ID (CUSAxxxxx)
   from the user's own copy. No decrypted eboot is provided here.
2. Find and validate the actual RAGE fiDevice/RPF8 or XML/META loader
   entrypoints for PS4 1.32; verify calling convention, return type,
   pointer lifetime, method offsets and original trampolines.
3. Protect hooks with version fingerprints and exact entry bytes; never
   reuse RDR2 1.00 offsets without checking them on 1.32.
4. Route ALL operations on overlay tokens, not just file Open:
   read, seek, size, stat, close. Never pass synthetic bridge tokens
   to unmodified engine functions.
5. Confirm that PS5 13.60 accepts the game PRX. A public issue documented
   an arena mprotect failure for RDR2 PS4 1.32 / CUSA08519 under one
   unofficial etaHEN fork (October 2026).
6. Implement RAGE XML/PSO conversion and streaming/data registration.
   These are not supplied by the current generic file bridge.

## Repository hygiene

- This GitHub repository is PUBLIC at the owner's request. Avoid committing personal paths or identifying data.
- Do not commit toolchain archives, proprietary LML ASI/DLL files,
  sample mod payloads, game/eboot binaries, RPF archives, credentials,
  access tokens, local logs or other sensitive machine information.
- Never modify unrelated original LML distribution files.
- Keep tests and status docs truthful about simulated vs console-tested work.
