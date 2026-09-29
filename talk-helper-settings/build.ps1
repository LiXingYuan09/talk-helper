param([switch]$SkipPanel,[string]$OutputDirectory='')
$ErrorActionPreference='Stop'
$compiler='C:\msys64\mingw64\bin\g++.exe'
$old=$env:PATH
try {
 $env:PATH=(Split-Path $compiler)+';'+$env:PATH
 $out=if($OutputDirectory){$OutputDirectory}else{Join-Path $PSScriptRoot 'bin'}
 New-Item -ItemType Directory -Path $out -Force | Out-Null
 $flags=@('-std=c++17','-O2','-Wall','-Wextra','-DUNICODE','-D_UNICODE','-DNOMINMAX','-D_WIN32_WINNT=0x0A00','-static','-static-libgcc','-static-libstdc++')
 if(!$SkipPanel){
  & $compiler @flags -shared (Join-Path $PSScriptRoot 'src/panel.cpp') -o (Join-Path $out 'TalkHelperNative-v13r2.dll') -luser32 -lgdi32 -lgdiplus -lbcrypt -ladvapi32 -lshlwapi -lole32 -lcomctl32
  if($LASTEXITCODE -ne 0){throw 'View build failed'}
 }
 & 'C:\msys64\mingw64\bin\windres.exe' -I (Join-Path $PSScriptRoot 'src') -i (Join-Path $PSScriptRoot 'src/probe.rc') -o (Join-Path $out 'probe-res.o')
 if($LASTEXITCODE -ne 0){throw 'Manifest build failed'}
 & $compiler @flags -municode -mwindows (Join-Path $PSScriptRoot 'src/controller.cpp') (Join-Path $out 'probe-res.o') -o (Join-Path $out 'TalkHelper-Native-v13.exe') -luser32 -lgdi32 -lversion -ladvapi32 -lshell32
 if($LASTEXITCODE -ne 0){throw 'Launcher build failed'}
 & $compiler @flags -DTALKHELPER_REMOVE -municode -mwindows (Join-Path $PSScriptRoot 'src/controller.cpp') (Join-Path $out 'probe-res.o') -o (Join-Path $out 'TalkHelper-Stop-v13r2.exe') -luser32 -lgdi32 -lversion -ladvapi32 -lshell32
 if($LASTEXITCODE -ne 0){throw 'Restore tool build failed'}
 & $compiler @flags -DTALKHELPER_REMOVE -DTALKHELPER_REMOVE_LEGACY -municode -mwindows (Join-Path $PSScriptRoot 'src/controller.cpp') (Join-Path $out 'probe-res.o') -o (Join-Path $out 'TalkHelper-Stop-v13.exe') -luser32 -lgdi32 -lversion -ladvapi32 -lshell32
 if($LASTEXITCODE -ne 0){throw 'Legacy restore tool build failed'}
 & $compiler @flags -DTALKHELPER_SETTINGS -municode -mwindows (Join-Path $PSScriptRoot 'src/controller.cpp') (Join-Path $out 'probe-res.o') -o (Join-Path $out 'TalkHelper-Settings-v13.exe') -luser32 -lgdi32 -lversion -ladvapi32 -lshell32
 if($LASTEXITCODE -ne 0){throw 'Settings launcher build failed'}
} finally {$env:PATH=$old}
