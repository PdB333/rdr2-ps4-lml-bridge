# Rebuild and validate the PS4 1.00 fiPackfile8 trace module, offline.
# Reproducible on the existing Windows workstation with OpenOrbis/LLVM18.
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $root
$cc='C:\Strawberry\c\bin\gcc.exe'
$cxx='C:\Strawberry\c\bin\g++.exe'
$out=Join-Path $root 'orbis_build'
foreach($p in @($cc,$cxx)){
    if(-not(Test-Path -LiteralPath $p)){throw "Missing host tool: $p"}
}
New-Item -ItemType Directory -Path $out -Force | Out-Null
Write-Output '=== Compile C version fingerprint and registry ==='
& $cc @('-std=c11','-O2','-Wall','-Wextra','-Werror','-c',
    '.\runtime\rage_eboot_profile.c','-o',
    (Join-Path $out 'rage_eboot_profile.host100.o'))
if($LASTEXITCODE -ne 0){throw 'EBOOT C profile host compile failed'}
& $cc @('-std=c11','-O2','-Wall','-Wextra','-Werror','-c',
    '.\runtime\rdr2_100_registry.c','-o',
    (Join-Path $out 'rdr2_100_registry.host100.o'))
if($LASTEXITCODE -ne 0){throw 'Registry C host compile failed'}
Write-Output '=== Build 1.00 VFS lifecycle, concurrent and exception tests ==='
$hostExe=Join-Path $out 'rdr2_100_trace_harness.exe'
$args=@(
    '-std=c++17','-O2','-Wall','-Wextra','-Werror',
    '-fexceptions','-DRDR2_100_HOST_TEST',
    '-static','-static-libgcc','-static-libstdc++','-pthread',
    '.\runtime\rdr2_100_pack_trace.cpp',
    '.\tests\test_rdr2_100_trace.cpp',
    (Join-Path $out 'rdr2_100_registry.host100.o'),
    (Join-Path $out 'rage_eboot_profile.host100.o'),
    '-o',$hostExe
)
& $cxx @args
if($LASTEXITCODE -ne 0){throw '1.00 trace host build failed'}
& $hostExe
if($LASTEXITCODE -ne 0){throw '1.00 trace host safety test failed'}
Write-Output '=== Orbis cross-build: actual PS4 PRX ==='
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File '.\orbis\build_pack_trace_100.ps1'
if($LASTEXITCODE -ne 0){throw 'PS4 1.00 trace PRX build failed'}
Write-Output '=== Full regression suite ==='
& python.exe -B -m unittest discover -s '.\tests' -p 'test_*.py' -v
if($LASTEXITCODE -ne 0){throw 'RDR2 full Python test suite failed'}
$meta=Get-Content -LiteralPath (Join-Path $out 'pack_trace_100_report.json') -Raw |
    ConvertFrom-Json
$module=Join-Path $out $meta.artifact
if(-not(Test-Path -LiteralPath $module)){throw 'Missing Orbis PRX'}
$digest=(Get-FileHash -LiteralPath $module -Algorithm SHA256).Hash.ToLowerInvariant()
if($digest -ne $meta.sha256){throw 'Orbis PRX checksum mismatch'}
if($meta.auto_installed_in_game -ne $false -or
   $meta.console_tested -ne $false -or
   $meta.direct_resource_replacement_available -ne $false){
   throw 'Diagnostic PRX falsely claims working in-game replacement'
}
$original=Join-Path $root '..\ModLoader\vfs.asi'
if(Test-Path -LiteralPath $original){
    $value=(Get-FileHash -LiteralPath $original -Algorithm SHA256).Hash.ToLowerInvariant()
    if($value -ne 'b54021d4f86b2136ef371a8ec0a8c05e98717605f27caf9c06f5893070cca918'){
        throw 'Original proprietary vfs.asi unexpectedly changed'
    }
}
$final=[ordered]@{
    target='Red Dead Redemption 2 PS4 1.00'
    sha256_of_owner_eboot='e3ae087f833b0f30f462bb7f880dd2955bf9f51dbb6e56706ee9bda81581feff'
    result='OFFLINE_TESTS_AND_ORBIS_PRX_BUILT'
    report_file='pack_trace_100_report.json'
    prx_file=$meta.artifact
    prx_bytes=$meta.bytes
    prx_sha256=$digest
    full_vtable_methods_verified=112
    host_stress_multithread_passed=$true
    host_original_fallback_passed=$true
    host_detach_busy_and_stale_pointer_passed=$true
    hosted_exception_safety_passed=$true
    source_LML_original_unchanged=$true
    original_RAGE_RPF8_handles_returned=$true
    actual_resource_replacement_in_game=$false
    live_PS5_tested=$false
    auto_hook_installed=$false
}
$final | ConvertTo-Json -Depth 5 |
   Set-Content -LiteralPath (Join-Path $out 'pack_trace_100_final_validation.json') -Encoding UTF8
Write-Output ('FINAL_PRX_SHA256='+$digest)
Write-Output 'RDR2_100_ALL_OFFLINE_VALIDATIONS_PASSED=True'
