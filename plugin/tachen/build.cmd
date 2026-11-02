@echo off
rem Build portable Windows du plugin TacHen LML (RDR2 PS4 1.00).
rem Recette verifiee le 2 nov. 2026 : clang(sie-ps5) -c, ld.lld --shared,
rem patch e_type -> ET_SCE_DYNAMIC, make_fself --ptype fake.
rem
rem Sur Windows, prospero-clang/-lld ne conviennent pas pour un objet partage :
rem   - les wrappers bin/* sont des scripts Linux ;
rem   - win/prospero-lld.exe ajoute -pie en dur (incompatible --shared).
rem On appelle donc clang + ld.lld directement avec les flags SCE du driver.
setlocal

if "%PS5_PAYLOAD_SDK%"=="" set PS5_PAYLOAD_SDK=C:\Users\Selat\ps5-tools\ps5-payload-sdk-extract\ps5-payload-sdk
if "%LLVMBIN%"=="" set LLVMBIN=C:\Users\Selat\ps5-tools\llvm\clang+llvm-23.1.4-x86_64-pc-windows-msvc\bin
set PATH=%LLVMBIN%;%PATH%
cd /d "%~dp0"

echo [1/4] compile sie-ps5 -^> lml_plugin.o
clang -target x86_64-sie-ps5 -isysroot "%PS5_PAYLOAD_SDK%" -isystem "%PS5_PAYLOAD_SDK%\target\include" ^
  -fno-stack-protector -fno-plt -femulated-tls -fPIC -Wall -g -c -o lml_plugin.o lml_plugin.c || exit /b 1

echo [2/4] link partage -^> lml_plugin.prx (ld.lld direct, sans -pie)
ld.lld -m elf_x86_64_fbsd --eh-frame-hdr --hash-style=sysv --build-id=uuid ^
  --unresolved-symbols=report-all -z now -z start-stop-visibility=hidden -z rodynamic ^
  -z common-page-size=0x4000 -z max-page-size=0x4000 ^
  --default-script "%PS5_PAYLOAD_SDK%\target\lib\prx.script" --shared -o lml_plugin.prx ^
  -L "%PS5_PAYLOAD_SDK%\target\lib" -l:crti.o -l:crtbeginS.o lml_plugin.o ^
  -lc -lkernel_web -lSceLibcInternal -lc_stub_weak -lkernel_stub_weak -l:crtendS.o -l:crtn.o || exit /b 1

echo [3/4] patch e_type ET_DYN -^> ET_SCE_DYNAMIC (0xfe18)
python "%~dp0patch_etype.py" lml_plugin.prx || exit /b 1

echo [4/4] fake-sign -^> lml_plugin.sprx (magic 0x1d3d154f)
python "%PS5_PAYLOAD_SDK%\samples\install_app\make_fself.py" --ptype fake lml_plugin.prx lml_plugin.sprx || exit /b 1

echo OK : lml_plugin.sprx pret pour TacHen (enregistrer sous RDR2 1.00).
endlocal
