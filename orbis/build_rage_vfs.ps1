# Compile the independent RAGE VFS read-through adapter for Orbis/PS4.
# Contains a fingerprint of a user-confirmed RDR2 PS4 1.00 EBOOT only.
# The 1.32 game hook remains disabled; do not use 1.00 RVAs for 1.32.
$ErrorActionPreference='Stop'
$project = Split-Path $PSScriptRoot -Parent
$build = Join-Path $project 'orbis_build'
$tc = Join-Path $project '.toolchains'
$sdk = Join-Path $tc 'OpenOrbis\PS4Toolchain'
$llvm = Join-Path $tc 'llvm18-minimal\bin'
$clang = Join-Path $llvm 'clang.exe'
$clangxx = Join-Path $llvm 'clang++.exe'
$ld = Join-Path $llvm 'ld.lld.exe'
$fself = Join-Path $sdk 'bin\windows\create-fself.exe'
$readelf = 'C:\Strawberry\c\bin\readelf.exe'
foreach($tool in @($clang,$clangxx,$ld,$fself,$readelf)){
    if(-not(Test-Path -LiteralPath $tool)){throw "Missing tool: $tool"}
}
New-Item -ItemType Directory -Path $build -Force | Out-Null
$env:OO_PS4_TOOLCHAIN = $sdk

$baseArgs=@('--target=x86_64-pc-freebsd12-elf',
    '-D_GNU_SOURCE','-D_POSIX_C_SOURCE=200809L',
    '-O2','-Wall','-Wextra','-Werror','-fPIC',
    '-funwind-tables','-fvisibility=hidden','-isysroot',$sdk,
    '-isystem',(Join-Path $sdk 'include'))
$cxxArgs=@('-std=c++17','-fexceptions','-nostdinc++',
           '-isystem',(Join-Path $sdk 'include\c++\v1'))
$source=@(
    @{Tool=$clangxx; Args=$cxxArgs; Name='rage_overlay_index'; File=(Join-Path $project 'runtime\overlay_index.cpp')},
    @{Tool=$clangxx; Args=$cxxArgs; Name='rage_vfs_redirect'; File=(Join-Path $project 'runtime\rage_vfs_redirect.cpp')},
    @{Tool=$clang; Args=@('-std=c11'); Name='rage_eboot_profile'; File=(Join-Path $project 'runtime\rage_eboot_profile.c')},
    @{Tool=$clang; Args=@('-std=c11'); Name='rage_vfs_module'; File=(Join-Path $PSScriptRoot 'rage_vfs_module.c')}
)
$objects=@()
foreach($item in $source){
    $object=Join-Path $build ($item.Name + '.vfs.o')
    & $item.Tool @($baseArgs + $item.Args + @('-c','-o',$object,$item.File))
    if($LASTEXITCODE -ne 0){throw ("Orbis compiler failed for "+$item.File)}
    $objects += $object
}

$elf=Join-Path $build 'rage_vfs_adapter.elf'
$oelf=Join-Path $build 'rage_vfs_adapter.oelf'
$prx=Join-Path $build 'LmlBridge_132_rage_vfs_adapter.prx'
$link=@('-m','elf_x86_64','-pie','--script',(Join-Path $sdk 'link.x'),
        '--eh-frame-hdr','--no-undefined','-e','_init',
        '--export-dynamic-symbol=lml_rage_*',
        '--export-dynamic-symbol=lml_eboot_*',
        '--export-dynamic-symbol=module_start',
        '--export-dynamic-symbol=module_stop',
        '-o',$elf) + $objects + @(
            ('-L'+(Join-Path $sdk 'lib')),
            '-lc','-lc++','-lc++abi','-lunwind','-lkernel','-lSceLibcInternal'
        )
& $ld @link
if($LASTEXITCODE -ne 0){throw 'Orbis VFS link failed'}

$dynamic=(& $readelf '--dyn-syms' '--wide' $elf | Out-String)
$symbols=@(
    'module_start','module_stop',
    'lml_rage_abi_version',
    'lml_rage_load_overlay',
    'lml_rage_bind_game_io',
    'lml_rage_open_file',
    'lml_rage_read_file',
    'lml_rage_read_at',
    'lml_rage_seek_file',
    'lml_rage_size_file',
    'lml_rage_close_file',
    'lml_rage_stat_path',
    'lml_rage_select_loader_path',
    'lml_rage_dispatch_text_loader',
    'lml_rage_get_counters',
    'lml_rage_clear',
    'lml_rage_game_hook_installed',
    'lml_rage_module_index_status',
    'lml_eboot_verify_profile'
)
foreach($symbol in $symbols){
    if($dynamic -notmatch ('(?m)\b'+[regex]::Escape($symbol)+'\s*$')){
        throw ('Missing Orbis export: '+$symbol)
    }
}
$fselfArgs=@(('-in='+$elf),('-out='+$oelf),('--lib='+$prx),
             '--paid','0x3800000000000011')
& $fself @fselfArgs
if($LASTEXITCODE -ne 0 -or -not(Test-Path $prx)){
    throw 'OpenOrbis create-fself did not produce a PRX'
}
$raw=[System.IO.File]::ReadAllBytes($prx)
if($raw.Length -lt 128 -or $raw[0] -ne 0x4f -or $raw[1] -ne 0x15 -or
   $raw[2] -ne 0x3d -or $raw[3] -ne 0x1d){
    throw 'Invalid Orbis SELF header'
}
$report=[ordered]@{
    format='lml-rage-vfs-adapter-prx/1'
    target='RDR2 PS4 1.32 on PS5 13.60'
    file=('orbis_build/'+[IO.Path]::GetFileName($prx))
    bytes=$raw.Length
    sha256=(Get-FileHash -LiteralPath $prx -Algorithm SHA256).Hash.ToLowerInvariant()
    exports=$symbols
    vfs_virtual_file_methods=@('open','read','read_at','seek','size','close','stat')
    file_replacement_engine_compiled=$true
    original_callbacks_required=$true
    actual_rage_hook_installed=$false
    title_verified_eboot_offsets_available=$false
    eboot_static_profile_available=$true
    profile_source_sha256='e3ae087f833b0f30f462bb7f880dd2955bf9f51dbb6e56706ee9bda81581feff'
    profile_source_game_version='1.00'
    profile_source_version_evidence='user_confirmed'
    profile_supports_target_game_1_32=$false
    profile_requires_running_game_version_check=$true
    profile_rva_verification_exported=$true
    game_patch_version_confirmed=$false
    tested_on_ps5=$false
    read_only_replacement_only=$true
    original_rpf_archives_modified=$false
    needs_RAGE_XML_conversion=$true
}
$report | ConvertTo-Json -Depth 7 |
    Set-Content -LiteralPath (Join-Path $build 'rage_vfs_report.json') -Encoding UTF8
Write-Output ('RAGE_VFS_ADAPTER_PRX='+$prx)
Write-Output ('RAGE_VFS_PRX_BYTES='+$raw.Length)
Write-Output ('RAGE_VFS_PRX_SHA256='+$report.sha256)
Write-Output ('RAGE_VFS_API_EXPORTS='+$symbols.Count)
Write-Output 'ORBIS_RAGE_VFS_BRIDGE_COMPILED_AND_VERIFIED=True'
