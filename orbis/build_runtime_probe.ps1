# Orbis PRX v2: C++ LML resolver and exported PS4 module_start.
# Offline-build diagnostic only. Does not hook the RDR2 RAGE/RPF engine.
$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
$build = Join-Path $project 'orbis_build'
$tc = Join-Path $project '.toolchains'
$sdk = Join-Path $tc 'OpenOrbis\PS4Toolchain'
$clang = Join-Path $tc 'llvm18-minimal\bin\clang.exe'
$clangxx = Join-Path $tc 'llvm18-minimal\bin\clang++.exe'
$ld = Join-Path $tc 'llvm18-minimal\bin\ld.lld.exe'
$readelf = 'C:\Strawberry\c\bin\readelf.exe'
$fself = Join-Path $sdk 'bin\windows\create-fself.exe'
foreach($exe in @($clang,$clangxx,$ld,$readelf,$fself)){
    if(-not(Test-Path $exe)){throw "Missing toolchain component: $exe"}
}
New-Item -ItemType Directory -Path $build -Force | Out-Null
$flags = @(
    '--target=x86_64-pc-freebsd12-elf',
    '-D_GNU_SOURCE','-D_POSIX_C_SOURCE=200809L',
    '-O2','-Wall','-Wextra','-Werror',
    '-fPIC','-funwind-tables','-fvisibility=hidden',
    '-isysroot',$sdk,'-isystem',(Join-Path $sdk 'include')
)
$cplusplus = @('-std=c++17','-fexceptions','-nostdinc++',
                 '-isystem',(Join-Path $sdk 'include\c++\v1'))
$source = @(
    @{Compiler=$clangxx; Flags=$cplusplus; Name='overlay_index'; File=(Join-Path $project 'runtime\overlay_index.cpp')},
    @{Compiler=$clangxx; Flags=$cplusplus; Name='lml_bridge_exports'; File=(Join-Path $PSScriptRoot 'lml_bridge_exports.cpp')},
    @{Compiler=$clang; Flags=@('-std=c11'); Name='bridge_runtime_module'; File=(Join-Path $PSScriptRoot 'bridge_runtime_module.c')}
)
$objects = @()
foreach($item in $source){
    $o = Join-Path $build ($item.Name + '.runtime.o')
    $args = $flags + $item.Flags + @('-c','-o',$o,$item.File)
    & $item.Compiler @args
    if($LASTEXITCODE -ne 0){throw ('Target compilation failed: '+$item.File)}
    $objects += $o
}

$elf = Join-Path $build 'lml_runtime_probe.elf'
$oelf = Join-Path $build 'lml_runtime_probe.oelf'
$prx = Join-Path $build 'LmlBridge_132_runtime_probe.prx'
$linkArgs = @(
    '-m','elf_x86_64','-pie','--script',(Join-Path $sdk 'link.x'),
    '--eh-frame-hdr','-e','_init','--no-undefined',
    '--export-dynamic-symbol=lml_bridge_*',
    '--export-dynamic-symbol=lml_runtime_*',
    '--export-dynamic-symbol=module_start',
    '--export-dynamic-symbol=module_stop',
    '-o',$elf
) + $objects + @(
    ('-L'+(Join-Path $sdk 'lib')),
    '-lc','-lc++','-lc++abi','-lunwind','-lkernel','-lSceLibcInternal'
)
& $ld @linkArgs
if ($LASTEXITCODE -ne 0) { throw 'Orbis game resolver link failed' }
$dynsym = (& $readelf '--dyn-syms' '--wide' $elf | Out-String)
$needed = (& $readelf '-d' $elf | Out-String)
$api = @(
    'module_start','module_stop',
    'lml_bridge_abi_version','lml_bridge_open',
    'lml_bridge_lookup_replace','lml_bridge_lookup_stream',
    'lml_bridge_lookup_data','lml_bridge_get_counts',
    'lml_bridge_get_last_error','lml_runtime_last_init_result'
)
foreach($s in $api){
    if($dynsym -notmatch ('(?m)\b'+[regex]::Escape($s)+'\s*$')){
        throw "Orbis dynamic export missing: $s"
    }
}
if($needed -notmatch 'libkernel.so'){
    throw 'Runtime probe does not reference libkernel'
}
$env:OO_PS4_TOOLCHAIN = $sdk
$fselfArgs = @(
    ('-in='+$elf),('-out='+$oelf),('--lib='+$prx),
    '--paid','0x3800000000000011'
)
& $fself @fselfArgs
if($LASTEXITCODE -ne 0 -or -not(Test-Path $prx)){
    throw 'OpenOrbis failed to produce runtime PRX'
}
$bytes = [System.IO.File]::ReadAllBytes($prx)
if($bytes.Length -lt 128 -or $bytes[0] -ne 0x4f -or
    $bytes[1] -ne 0x15 -or $bytes[2] -ne 0x3d -or $bytes[3] -ne 0x1d){
    throw 'Runtime probe has invalid Orbis SELF header'
}
$report = [ordered]@{
    format = 'lml-orbis-runtime-loader-probe/1'
    game = 'RDR2 PS4 1.32'
    console_firmware = 'PS5 13.60'
    module = $prx
    sha256 = (Get-FileHash -LiteralPath $prx -Algorithm SHA256).Hash.ToLowerInvariant()
    bytes = $bytes.Length
    exported_symbols = $api
    dynamic_libraries = @('libkernel.so','libSceLibcInternal.so')
    map_path = '/data/etaHEN/lml_bridge/overlay.map'
    root_path = '/data/etaHEN/lml_bridge'
    module_start_exported = $true
    cpp_constructor_array_called_in_module_start = $true
    reads_map_on_start = $true
    patches_game_memory = $false
    hooks_RAGE_RPF = $false
    tested_on_console = $false
    validated_in_game = $false
}
$report | ConvertTo-Json -Depth 6 |
    Set-Content -LiteralPath (Join-Path $build 'runtime_probe_report.json') -Encoding UTF8
Write-Output ('RUNTIME_PROBE_PRX='+$prx)
Write-Output ('RUNTIME_PROBE_SHA256='+$report.sha256)
Write-Output ('RUNTIME_PROBE_BYTES='+$report.bytes)
Write-Output ('EXPORTED_SYMBOLS='+$api.Count)
Write-Output 'ORBIS_CPP_RUNTIME_PRX_BUILD_PASSED=True'
