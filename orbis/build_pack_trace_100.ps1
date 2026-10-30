# Standalone PS4 1.00 fiPackfile8 trace PRX (passive by default).
$ErrorActionPreference = 'Stop'
$project=Split-Path $PSScriptRoot -Parent
$build=Join-Path $project 'orbis_build'
$sdk=Join-Path $project '.toolchains\OpenOrbis\PS4Toolchain'
$bin=Join-Path $project '.toolchains\llvm18-minimal\bin'
$clang=Join-Path $bin 'clang.exe'
$clangxx=Join-Path $bin 'clang++.exe'
$lld=Join-Path $bin 'ld.lld.exe'
$readelf='C:\Strawberry\c\bin\readelf.exe'
$fself=Join-Path $sdk 'bin\windows\create-fself.exe'
foreach($item in @($clang,$clangxx,$lld,$readelf,$fself,(Join-Path $sdk 'link.x'))) {
    if(-not(Test-Path -LiteralPath $item)){throw "Missing Orbis tool: $item"}
}
New-Item -ItemType Directory -Path $build -Force | Out-Null
$base=@(
    '--target=x86_64-pc-freebsd12-elf',
    '-D_GNU_SOURCE','-D_POSIX_C_SOURCE=200809L','-O2',
    '-Wall','-Wextra','-Werror','-fPIC','-funwind-tables',
    '-fvisibility=hidden','-isysroot',$sdk,
    '-isystem',(Join-Path $sdk 'include')
)
$cxx=@('-std=c++17','-fexceptions','-nostdinc++',
       '-isystem',(Join-Path $sdk 'include\c++\v1'))
$sources=@(
    @{Compiler=$clangxx; Args=$cxx; Name='trace100'; Path=(Join-Path $project 'runtime\rdr2_100_pack_trace.cpp')},
    @{Compiler=$clang; Args=@('-std=c11'); Name='registry100'; Path=(Join-Path $project 'runtime\rdr2_100_registry.c')},
    @{Compiler=$clang; Args=@('-std=c11'); Name='profile100'; Path=(Join-Path $project 'runtime\rage_eboot_profile.c')},
    @{Compiler=$clang; Args=@('-std=c11'); Name='module100'; Path=(Join-Path $PSScriptRoot 'pack_trace_100_module.c')}
)
$objects=@()
foreach($source in $sources){
    $dest=Join-Path $build ($source.Name+'.orbis.o')
    & $source.Compiler @($base+$source.Args+@('-c','-o',$dest,$source.Path))
    if($LASTEXITCODE -ne 0){throw ('Orbis compile failed: '+$source.Name)}
    $objects+=$dest
}
$elf=Join-Path $build 'pack_trace_100.elf'
$oelf=Join-Path $build 'pack_trace_100.oelf'
$prx=Join-Path $build 'LmlBridge_RDR2_PS4_100_fiPackfile8_trace.prx'
$exports=@(
    'module_start','module_stop',
    'lml_rdr2_100_trace_abi_version',
    'lml_rdr2_100_trace_autohook_installed',
    'lml_eboot_verify_profile',
    'rdr2_100_find_pack_instances',
    'rdr2_100_pack_preflight',
    'rdr2_100_pack_trace_attach_checked',
    'rdr2_100_pack_trace_detach',
    'rdr2_100_pack_trace_is_attached',
    'rdr2_100_pack_trace_open_calls',
    'rdr2_100_pack_trace_active_calls',
    'rdr2_100_pack_trace_may_unload'
)
$link=@('-m','elf_x86_64','-pie','--script',(Join-Path $sdk 'link.x'),
        '--eh-frame-hdr','--no-undefined','-e','_init',
        '--export-dynamic-symbol=lml_eboot_*',
        '--export-dynamic-symbol=lml_rdr2_100_*',
        '--export-dynamic-symbol=rdr2_100_*',
        '--export-dynamic-symbol=module_start',
        '--export-dynamic-symbol=module_stop',
        '-o',$elf)+$objects+@(
        ('-L'+(Join-Path $sdk 'lib')),
        '-lc','-lc++','-lc++abi','-lunwind','-lkernel','-lSceLibcInternal'
        )
& $lld @link
if($LASTEXITCODE -ne 0){throw 'Orbis 1.00 trace PRX link failed'}
$dyn=(& $readelf '--dyn-syms' '--wide' $elf | Out-String)
if($LASTEXITCODE -ne 0){throw 'readelf --dyn-syms failed'}
foreach($symbol in $exports){
    if($dyn -notmatch ('(?m)\b'+[regex]::Escape($symbol)+'\s*$')){
        throw "Orbis trace export missing: $symbol"
    }
}
if($dyn -match '\brdr2_100_pack_trace_host_fixture_attach\s*$'){
    throw 'Host-only bypass accidentally exported to PS4'
}
$needed=(& $readelf '-d' $elf | Out-String)
if($LASTEXITCODE -ne 0 -or $needed -notmatch 'libkernel.so'){
    throw 'Missing libkernel shared library'
}
$env:OO_PS4_TOOLCHAIN=$sdk
$fselfArgs=@(('-in='+$elf),('-out='+$oelf),('--lib='+$prx),
             '--paid','0x3800000000000011')
& $fself @fselfArgs
if($LASTEXITCODE -ne 0 -or -not(Test-Path $prx)){
    throw 'OpenOrbis create-fself failed'
}
$raw=[IO.File]::ReadAllBytes($prx)
if($raw.Length -lt 128 -or $raw[0] -ne 0x4f -or $raw[1] -ne 0x15 -or
   $raw[2] -ne 0x3d -or $raw[3] -ne 0x1d){
    throw 'Orbis SELF header invalid'
}
$report=[ordered]@{
    artifact='LmlBridge_RDR2_PS4_100_fiPackfile8_trace.prx'
    profile_game='RDR2 PS4 1.00'
    profile_source_eboot_sha256='e3ae087f833b0f30f462bb7f880dd2955bf9f51dbb6e56706ee9bda81581feff'
    profile_vtable_slots=112
    profile_vtable_fnv64='8eaecb696678dad0'
    bytes=$raw.Length
    sha256=(Get-FileHash -LiteralPath $prx -Algorithm SHA256).Hash.ToLowerInvariant()
    exported_symbols=$exports
    host_only_fixture_not_exported=$true
    version_1_32_rejected_before_memory_read=$true
    auto_installed_in_game=$false
    read_only_trace_only=$true
    direct_resource_replacement_available=$false
    requires_validated_game_base_and_pinned_instance=$true
    requires_module_to_remain_loaded_after_attach=$true
    console_tested=$false
}
$report|ConvertTo-Json -Depth 6 |
  Set-Content -LiteralPath (Join-Path $build 'pack_trace_100_report.json') -Encoding utf8
Write-Output ('PS4_100_TRACE_PRX='+$prx)
Write-Output ('PS4_100_TRACE_SHA256='+$report.sha256)
Write-Output ('PS4_100_TRACE_BYTES='+$report.bytes)
Write-Output ('PS4_100_TRACE_EXPORTS='+$exports.Count)
Write-Output 'PS4_100_TRACE_ORBIS_BUILD_PASSED=True'
