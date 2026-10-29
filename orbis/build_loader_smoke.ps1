# Produce a minimal Orbis PRX with no game hooks or C++ runtime.
$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
$toolchains = Join-Path $project '.toolchains'
$sdk = Join-Path $toolchains 'OpenOrbis\PS4Toolchain'
$clang = Join-Path $toolchains 'llvm18-minimal\bin\clang.exe'
$lld = Join-Path $toolchains 'llvm18-minimal\bin\ld.lld.exe'
$fself = Join-Path $sdk 'bin\windows\create-fself.exe'
$readelf = 'C:\Strawberry\c\bin\readelf.exe'
$out = Join-Path $project 'orbis_build'
foreach ($tool in @($clang,$lld,$fself,$readelf,(Join-Path $sdk 'lib\crtlib.o'))) {
    if (-not (Test-Path $tool)) { throw "Missing PS4 tool: $tool" }
}
New-Item -ItemType Directory -Path $out -Force | Out-Null
$env:OO_PS4_TOOLCHAIN = $sdk
$obj = Join-Path $out 'loader_smoke.o'
$elf = Join-Path $out 'loader_smoke.elf'
$oelf = Join-Path $out 'loader_smoke.oelf'
$prx = Join-Path $out 'LmlBridge_132_loader_smoke.prx'
$ccArgs = @(
    '--target=x86_64-pc-freebsd12-elf','-fPIC','-O2','-c',
    '-o',$obj,(Join-Path $PSScriptRoot 'loader_smoke.c')
)
& $clang @ccArgs
if ($LASTEXITCODE -ne 0) { throw 'PS4 smoke object compile failed' }
$linkArgs = @(
    '-m','elf_x86_64','-pie',
    '--script',(Join-Path $sdk 'link.x'),
    '-e','_init','--export-dynamic-symbol=lml_probe_*',
    '-o',$elf,$obj,(Join-Path $sdk 'lib\crtlib.o'),
    ('-L' + (Join-Path $sdk 'lib')),'-lkernel'
)
& $lld @linkArgs
if ($LASTEXITCODE -ne 0) { throw 'PS4 smoke ELF link failed' }
$symbols = (& $readelf '--dyn-syms' '--wide' $elf | Out-String)
foreach($name in @('lml_probe_identity','lml_probe_abi_version')){
    if($symbols -notmatch ('(?m)\b'+[regex]::Escape($name)+'\s*$')){
        throw "Smoke PRX missing exported ABI: $name"
    }
}
$fselfArgs = @(
    ('-in=' + $elf),
    ('-out=' + $oelf),
    ('--lib=' + $prx),
    '--paid','0x3800000000000011'
)
& $fself @fselfArgs
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $prx)) {
    throw 'PS4 smoke PRX creation failed'
}
$bytes = [System.IO.File]::ReadAllBytes($prx)
if ($bytes.Length -lt 128 -or $bytes[0] -ne 0x4f -or $bytes[1] -ne 0x15 -or
    $bytes[2] -ne 0x3d -or $bytes[3] -ne 0x1d) {
    throw 'Smoke module does not have Orbis SELF header'
}
$report=[ordered]@{
    target = 'RDR2 PS4 1.32 on PS5 13.60'
    filename = $prx
    bytes = $bytes.Length
    sha256 = (Get-FileHash $prx -Algorithm SHA256).Hash.ToLowerInvariant()
    exported_symbols = @('lml_probe_identity','lml_probe_abi_version')
    module_uses_game_hooks = $false
    tested_on_console = $false
}
$report | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $out 'loader_smoke_report.json') -Encoding utf8
Write-Output ('SMOKE_PRX='+$prx)
Write-Output ('SMOKE_PRX_BYTES='+$report.bytes)
Write-Output ('SMOKE_PRX_SHA256='+$report.sha256)
Write-Output 'ORBIS_SMOKE_BUILD_PASSED=True'
