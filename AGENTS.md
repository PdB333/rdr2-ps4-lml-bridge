# Project handoff for coding agents

## Goal and status

Build an independent LML-style file replacement bridge for Red Dead
Redemption 2 on a **PS5 firmware 13.60 jailbreak**. Work on **PS4 1.00
FIRST** using the owner-confirmed EBOOT (SHA-256 e3ae087f...), then
support PS4 1.32 using a separate EBOOT and version profile. Focus on offline story mode.

The source and Orbis PRX compile successfully. This is **NOT a functioning
in-game modloader yet**. The RAGE/RPF8 read-through replacement and XML/text
loader callback are tested against a simulated original RAGE VFS only.
Version-specific interception of RDR2 PS4 1.32 has NOT been installed.
The exported lml_rage_game_hook_installed() currently returns 0.

Do not report simulated success as a successful in-game hook.

## Current PS4 1.00 deliverable (October 30, 2026)

`orbis/build_pack_trace_100.ps1` produces a real Orbis PRX named
`LmlBridge_RDR2_PS4_100_fiPackfile8_trace.prx` (local, Git-ignored).
It does **not** auto-install a game hook. A carefully gated one-instance
fiPackfile8 Open observer is implemented in `runtime/rdr2_100_pack_trace.*`,
with a bounded registry probe in `runtime/rdr2_100_registry.*` and a
full 112-slot vtable identity check. Retired shadow tables are never reused;
once attached, the PRX must stay resident for the process lifetime. The
owner's 1.00 code was checked by hash and method identity, but real-game
object lifetime, plugin injection, and RPF8 replacement still require testing.

Run `tools/verify_pack_trace_100.ps1` from the repo root for the host stress
tests, Orbis PRX, and full unit suite. Detailed engineering status is in
`orbis/RDR2_PS4_100_TRACE_STATUS.md`. Do not describe this as a working
file modloader; **Open tracing is not byte replacement**.

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
- orbis/RDR2_PS4_100_TRACE_STATUS.md: authoritative one-version hook boundary,
  zero game writes on module_start, safety/lifetime conditions and results.
- tools/verify_eboot_100.py: independent verification of the original user
  EBOOT, all 112 vtable function pointers and source SHA-256.
- tools/verify_pack_trace_100.ps1: cross compile and full host validation.

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

The Windows project currently passes 54 offline tests (including the EBOOT fingerprint guard). A fresh
clone needs the locally installed SDK and generated host test executables
for full test coverage; missing build outputs can cause skips or errors.

## Remaining tasks

1. A user-supplied **RDR2 PS4 1.00** ELF was inspected privately (121670745 bytes,
   SHA-256 e3ae087f833b0f30f462bb7f880dd2955bf9f51dbb6e56706ee9bda81581feff).
   The ELF itself must never be uploaded. The user explicitly confirmed it is
   version 1.00, NOT 1.32. The Title ID CUSA remains unknown. See orbis/EBOOT_RAGE_VFS_PROFILE.md and
   tools/inspect_rdr2_eboot.py for reproducible static evidence.
2. The **1.00** upload contains fiPackfile8 RTTI/vtable RVA 0x066B00F8
   and candidate Open at 0x0452A480. runtime/rage_eboot_profile.c now requires
   (game_major=1, game_minor=0), rejecting 1.32 before any memory read.
   These 1.00 offsets are NOT verified for 1.32. Complete ABI analysis,
   original trampolines and a separate 1.32 EBOOT are still needed.
3. Protect hooks with version fingerprints and exact entry bytes; never
   reuse RDR2 1.00 offsets without checking them on 1.32.
   NEVER activate a hook just because the new guard matches this ELF.
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

## Static EBOOT analysis (October 2026)

A small, sanitized **RDR2 PS4 1.00 ONLY** fiPackfile8 profile is included.
The proprietary 121.7 MB EBOOT was analyzed outside GitHub and was not
checked into the repo. NEVER apply its 1.00 offsets to game update 1.32. The current PRX has 19 exports and the actual
hook-installed status remains false.
