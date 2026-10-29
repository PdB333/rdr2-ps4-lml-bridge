# Build a diagnostic LML overlay resolver PRX for PS4/Orbis on Windows.
# Does NOT install anything on a PS5, hook RDR2, or convert LML's proprietary vfs.asi.
$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
$toolchains = Join-Path $project '.toolchains'
$sdk = Join-Path $toolchains 'OpenOrbis\PS4Toolchain'
$llvm = Join-Path $toolchains 'llvm18-minimal\bin'
$cc = Join-Path $llvm 'clang++.exe'
$ld = Join-Path $llvm 'ld.lld.exe'
$fself = Join-Path $sdk 'bin\windows\create-fself.exe'
$readelf = 'C:\Strawberry\c\bin\readelf.exe'
$out = Join-Path $project 'orbis_build'
foreach ($path in @($cc, $ld, $fself, $readelf, (Join-Path $sdk 'lib\crtlib.o'))) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing toolchain component: $path" }
}
New-Item -ItemType Directory -Path $out -Force | Out-Null
$env:OO_PS4_TOOLCHAIN = $sdk

$common = @(
    '--target=x86_64-pc-freebsd12-elf',
    '-D_GNU_SOURCE',
    '-D_POSIX_C_SOURCE=200809L',
    '-std=c++17',
    '-O2', '-Wall', '-Wextra',
    '-fPIC', '-funwind-tables', '-fexceptions', '-fvisibility=hidden',
    '-nostdinc++', '-isysroot', $sdk,
    '-isystem', (Join-Path $sdk 'include'),
    '-isystem', (Join-Path $sdk 'include\c++\v1')
)
$overlaySource = Join-Path $project 'runtime\overlay_index.cpp'
$apiSource = Join-Path $PSScriptRoot 'lml_bridge_exports.cpp'
$objects = @(
    @{ Source = $overlaySource; Object = (Join-Path $out 'overlay_index.o') },
    @{ Source = $apiSource; Object = (Join-Path $out 'lml_bridge_exports.o') }
)
foreach ($item in $objects) {
    & $cc @common '-c' '-o' $item.Object $item.Source
    if ($LASTEXITCODE -ne 0) { throw "PS4-target compile failed: $($item.Source)" }
}

$elf = Join-Path $out 'lml_bridge_api.elf'
$intermediate = Join-Path $out 'lml_bridge_api.oelf'
$prx = Join-Path $out 'LmlBridge_132_api_probe.prx'
$linkArgs = @(
    '-m', 'elf_x86_64', '-pie',
    '--script', (Join-Path $sdk 'link.x'),
    '--eh-frame-hdr', '-e', '_init',
    '--export-dynamic-symbol=lml_bridge_*',
    '-o', $elf,
    $objects[0].Object, $objects[1].Object,
    (Join-Path $sdk 'lib\crtlib.o'),
    ('-L' + (Join-Path $sdk 'lib')),
    '-lc', '-lc++', '-lc++abi', '-lunwind', '-lkernel', '-lSceLibcInternal'
)
& $ld @linkArgs
if ($LASTEXITCODE -ne 0) { throw 'PS4/Orbis ELF link failed' }

$symbols = (& $readelf '--dyn-syms' '--wide' $elf | Out-String)
$apiNames = @(
    'lml_bridge_abi_version',
    'lml_bridge_open',
    'lml_bridge_lookup_replace',
    'lml_bridge_lookup_stream',
    'lml_bridge_lookup_data',
    'lml_bridge_get_counts',
    'lml_bridge_get_last_error'
)
foreach ($name in $apiNames) {
    if ($symbols -notmatch ('(?m)\b' + [regex]::Escape($name) + '\s*$')) {
        throw "Orbis dynamic symbol not exported: $name"
    }
}

$fselfArgs = @(
    ('-in=' + $elf),
    ('-out=' + $intermediate),
    ('--lib=' + $prx),
    '--paid', '0x3800000000000011'
)
& $fself @fselfArgs
if ($LASTEXITCODE -ne 0) { throw 'OpenOrbis create-fself failed' }
if (-not (Test-Path -LiteralPath $prx)) { throw 'OpenOrbis produced no PRX file' }

$bytes = [System.IO.File]::ReadAllBytes($prx)
if ($bytes.Length -lt 128 -or $bytes[0] -ne 0x4F -or $bytes[1] -ne 0x15 -or
    $bytes[2] -ne 0x3D -or $bytes[3] -ne 0x1D) {
    throw 'PRX has an unexpected SELF header signature'
}

$report = [ordered]@{
    format = 'lml-bridge/orbis-build-check/1'
    target = 'RDR2 PS4 1.32'
    host_firmware = 'PS5 13.60'
    source = 'independent LML overlay resolver'
    output = $prx
    sha256 = (Get-FileHash -LiteralPath $prx -Algorithm SHA256).Hash.ToLowerInvariant()
    bytes = (Get-Item -LiteralPath $prx).Length
    dynamic_exports = $apiNames
    target_format = 'Orbis SELF PRX'
    created_with = 'OpenOrbis 0.5.4; LLVM 18.1.8'
    host_abi_regression = 'Run orbis/bridge_api_probe.cpp test on Windows'
    game_rpf_hook_implemented = $false
    tested_in_rdr2_ps4 = $false
    tested_on_ps5 = $false
    loader_compatibility_proven = $false
}
$reportFile = Join-Path $out 'build_report.json'
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportFile -Encoding utf8
Write-Output ('PRX=' + $prx)
Write-Output ('SHA256=' + $report.sha256)
Write-Output ('BYTES=' + $report.bytes)
Write-Output ('EXPORTED_ABI_FUNCTIONS=' + $apiNames.Count)
Write-Output 'ORBIS_BUILD_VERIFIED=True'
