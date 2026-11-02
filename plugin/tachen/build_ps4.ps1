# Build PS4 du plugin TacHen « preuve de vie » (RDR2 est un titre PS4).
# Chaine OpenOrbis, identique a orbis/build_pack_trace_100.ps1 : le loader
# kernel refusait le module PS5 (sie-ps5) avec EINVAL (0x80020016). Un vrai PRX
# PS4 (cible freebsd12-elf + create-fself) est le format attendu.
$ErrorActionPreference = 'Stop'
# plugin/tachen -> plugin -> racine projet
$project = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$build   = Join-Path $project 'orbis_build'
$sdk     = Join-Path $project '.toolchains\OpenOrbis\PS4Toolchain'
$bin     = Join-Path $project '.toolchains\llvm18-minimal\bin'
$clang   = Join-Path $bin 'clang.exe'
$lld     = Join-Path $bin 'ld.lld.exe'
$readelf = 'C:\Strawberry\c\bin\readelf.exe'
$fself   = Join-Path $sdk 'bin\windows\create-fself.exe'
foreach ($item in @($clang,$lld,$readelf,$fself,(Join-Path $sdk 'link.x'))) {
    if (-not (Test-Path -LiteralPath $item)) { throw "Missing Orbis tool: $item" }
}
New-Item -ItemType Directory -Path $build -Force | Out-Null

$base = @(
    '--target=x86_64-pc-freebsd12-elf',
    '-D_GNU_SOURCE','-D_POSIX_C_SOURCE=200809L','-O2',
    '-Wall','-Wextra','-Werror','-fPIC','-funwind-tables',
    '-fvisibility=hidden','-isysroot',$sdk,
    '-isystem',(Join-Path $sdk 'include'),'-std=c11'
)
$src = Join-Path $PSScriptRoot 'lml_plugin.c'
$obj = Join-Path $build 'lml_plugin_ps4.o'
& $clang @($base + @('-c','-o',$obj,$src))
if ($LASTEXITCODE -ne 0) { throw 'PS4 compile failed' }

$elf  = Join-Path $build 'lml_plugin_ps4.elf'
$oelf = Join-Path $build 'lml_plugin_ps4.oelf'
$prx  = Join-Path $build 'lml_plugin_ps4.prx'
# crtlib.o fournit module_start/module_stop/_init/_fini + .data.sce_module_param
# (disposition propre, sans duplicata create-fself). Notre code tourne via
# .init_array (constructeur). On n'edite PAS de libc (son .bss relance le
# dedoublement). Recette alignee sur orbis/build_loader_smoke.ps1.
$link = @('-m','elf_x86_64','-pie','--script',(Join-Path $sdk 'link.x'),
          '-e','_init',
          '-o',$elf,$obj,(Join-Path $sdk 'lib\crtlib.o'),
          ('-L'+(Join-Path $sdk 'lib')),
          '-lkernel')
& $lld @link
if ($LASTEXITCODE -ne 0) { throw 'PS4 link failed' }

# module_start/module_stop viennent du CRT (visibilite HIDDEN) : create-fself
# --lib les publie dans la table d'export SCE du module, pas en .dynsym. On
# verifie donc leur presence dans la table de symboles ELF.
$syms = (& $readelf '--syms' '--wide' $elf | Out-String)
foreach ($symbol in @('module_start','module_stop')) {
    if ($syms -notmatch ('\b'+[regex]::Escape($symbol)+'\b')) {
        throw "PS4 symbol missing: $symbol"
    }
}
$env:OO_PS4_TOOLCHAIN = $sdk
& $fself @(('-in='+$elf),('-out='+$oelf),('--lib='+$prx),'--paid','0x3800000000000011')
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $prx)) { throw 'create-fself failed' }

$raw = [IO.File]::ReadAllBytes($prx)
if ($raw.Length -lt 128 -or $raw[0] -ne 0x4f -or $raw[1] -ne 0x15 -or
    $raw[2] -ne 0x3d -or $raw[3] -ne 0x1d) { throw 'SELF header invalid' }
Write-Output ('PS4_PRX='+$prx)
Write-Output ('PS4_PRX_BYTES='+$raw.Length)
Write-Output ('PS4_PRX_SHA256='+(Get-FileHash -LiteralPath $prx -Algorithm SHA256).Hash.ToLowerInvariant())
Write-Output 'PS4_BUILD_PASSED=True'
