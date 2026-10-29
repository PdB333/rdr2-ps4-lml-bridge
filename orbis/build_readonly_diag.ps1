# Build self-contained Orbis/PS4 diagnostic PRX and Windows host probe.
# Game process: debug logs + read-only overlay.map access; NO hooks/patches.
$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
$build = Join-Path $project 'orbis_build'
$tc = Join-Path $project '.toolchains'
$sdk = Join-Path $tc 'OpenOrbis\PS4Toolchain'
$llvm = Join-Path $tc 'llvm18-minimal\bin'
$clang = Join-Path $llvm 'clang.exe'
$ld = Join-Path $llvm 'ld.lld.exe'
$gcc = 'C:\Strawberry\c\bin\gcc.exe'
$readelf = 'C:\Strawberry\c\bin\readelf.exe'
$fself = Join-Path $sdk 'bin\windows\create-fself.exe'
foreach ($tool in @($clang,$ld,$gcc,$readelf,$fself)) {
    if (-not (Test-Path -LiteralPath $tool)) { throw "Missing required tool: $tool" }
}
New-Item -ItemType Directory -Path $build -Force | Out-Null

$core = Join-Path $PSScriptRoot 'diag_probe_core.c'
$hostSource = Join-Path $PSScriptRoot 'host_diag_probe.c'
$source = Join-Path $PSScriptRoot 'loader_diag_module.c'
$exe = Join-Path $build 'host_diag_probe.exe'
Write-Output '=== Compile host test probe ==='
$hostArgs = @('-std=c11','-O2','-Wall','-Wextra','-Werror',
              '-static','-o',$exe,$core,$hostSource)
& $gcc @hostArgs
if ($LASTEXITCODE -ne 0) { throw 'Host diagnostic build failed' }

$common = @(
    '--target=x86_64-pc-freebsd12-elf',
    '-D_GNU_SOURCE',
    '-std=c11','-O2','-Wall','-Wextra','-Werror',
    '-fPIC','-ffreestanding','-fno-stack-protector','-fno-builtin',
    '-fno-unwind-tables','-fvisibility=hidden',
    '-isysroot',$sdk,'-isystem',(Join-Path $sdk 'include')
)
Write-Output '=== Compile isolated PS4 C module ==='
$coreObj = Join-Path $build 'diag_probe_core.o'
$modObj = Join-Path $build 'loader_diag_module.o'
& $clang @common '-c' '-o' $coreObj $core
if ($LASTEXITCODE -ne 0) { throw 'Orbis diagnostic core compilation failed' }
& $clang @common '-c' '-o' $modObj $source
if ($LASTEXITCODE -ne 0) { throw 'Orbis diagnostic entrypoint compilation failed' }

$elf = Join-Path $build 'lml_readonly_diag.elf'
$oelf = Join-Path $build 'lml_readonly_diag.oelf'
$prx = Join-Path $build 'LmlBridge_132_readonly_diagnostic.prx'
$linkArgs = @(
    '-m','elf_x86_64','-pie','--script',(Join-Path $sdk 'link.x'),
    '-e','_init','--no-undefined',
    '--export-dynamic-symbol=module_start',
    '--export-dynamic-symbol=module_stop',
    '--export-dynamic-symbol=lml_diag_*',
    '-o',$elf,$modObj,$coreObj,
    ('-L' + (Join-Path $sdk 'lib')),'-lkernel'
)
& $ld @linkArgs
if ($LASTEXITCODE -ne 0) { throw 'Orbis diagnostic ELF link failed' }

$symbols = (& $readelf '--dyn-syms' '--wide' $elf | Out-String)
$expected = @('module_start','module_stop','lml_diag_identity',
              'lml_diag_abi_version','lml_diag_last_status')
foreach ($name in $expected) {
    if ($symbols -notmatch ('(?m)\b'+[regex]::Escape($name)+'\s*$')) {
        throw "Required exported entrypoint missing: $name"
    }
}
$needed = (& $readelf '-d' $elf | Out-String)
if ($needed -notmatch 'libkernel.so') {
    throw 'Minimal PRX does not link against libkernel.so'
}
if ($needed -match 'libc\+\+|libSceLibcInternal') {
    throw 'Minimal C PRX unexpectedly depends on C++/libc internals'
}

$env:OO_PS4_TOOLCHAIN = $sdk
$fselfArgs=@(
    ('-in='+$elf),('-out='+$oelf),('--lib='+$prx),
    '--paid','0x3800000000000011'
)
& $fself @fselfArgs
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $prx)) {
    throw 'OpenOrbis create-fself failed'
}
$raw=[System.IO.File]::ReadAllBytes($prx)
if ($raw.Length -lt 128 -or $raw[0] -ne 0x4f -or $raw[1] -ne 0x15 -or
    $raw[2] -ne 0x3d -or $raw[3] -ne 0x1d) {
    throw 'Malformed Orbis SELF header'
}
$report=[ordered]@{
    format = 'lml-ps4-orbis-readonly-diagnostic/1'
    target_game = 'RDR2 PS4 1.32'
    target_firmware = 'PS5 13.60'
    module = $prx
    bytes = $raw.Length
    sha256 = (Get-FileHash -LiteralPath $prx -Algorithm SHA256).Hash.ToLowerInvariant()
    exported_symbols = $expected
    dynamic_needed = @('libkernel.so')
    default_map_path = '/data/etaHEN/lml_bridge/overlay.map'
    emitted_logs = @('MODULE_ENTRY','MAP_OK|MAP_UNAVAILABLE|MAP_BAD_*','MODULE_STOP')
    reads_game_files = $false
    writes_any_files = $false
    patches_game_memory = $false
    has_RAGE_file_hooks = $false
    console_tested = $false
}
$report | ConvertTo-Json -Depth 5 |
    Set-Content -LiteralPath (Join-Path $build 'readonly_diag_report.json') -Encoding UTF8
Write-Output ('DIAGNOSTIC_PRX='+$prx)
Write-Output ('DIAGNOSTIC_PRX_SHA256='+$report.sha256)
Write-Output ('DIAGNOSTIC_PRX_BYTES='+$raw.Length)
Write-Output ('EXPORTED_ENTRYPOINTS='+$expected.Count)
Write-Output 'ORBIS_READONLY_DIAGNOSTIC_BUILD_PASSED=True'
