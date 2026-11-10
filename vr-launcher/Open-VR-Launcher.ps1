param([switch]$Open)
$ErrorActionPreference='Stop'
$TaskRoot=$PSScriptRoot
$Pointer=Get-Content -LiteralPath (Join-Path $TaskRoot 'launcher-ui/active.json') -Raw | ConvertFrom-Json
if($Pointer.version -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$' -or $Pointer.version.Contains('..')){throw 'Invalid launcher version'}
$Package=Join-Path $TaskRoot ('launcher-ui/versions/'+$Pointer.version)
foreach($Name in @('bundle.json','vr-launcher.json')){
 $Pin=if($Name -eq 'bundle.json'){$Pointer.bundle_sha256}else{$Pointer.marker_sha256}
 if((Get-FileHash -LiteralPath (Join-Path $Package $Name) -Algorithm SHA256).Hash -ne $Pin){throw 'Launcher binding changed'}
}
$Bundle=Get-Content -LiteralPath (Join-Path $Package 'bundle.json') -Raw | ConvertFrom-Json
foreach($File in $Bundle.files.PSObject.Properties){
 if($File.Name.Contains('..') -or $File.Name.Contains(':') -or $File.Name.Contains('\') -or $File.Name.StartsWith('/')){throw 'Invalid launcher file path'}
 if((Get-FileHash -LiteralPath (Join-Path $Package $File.Name) -Algorithm SHA256).Hash -ne $File.Value){throw ('Launcher file changed: '+$File.Name)}
}
$Marker=Get-Content -LiteralPath (Join-Path $Package 'vr-launcher.json') -Raw | ConvertFrom-Json
$Protection=Join-Path $TaskRoot 'launcher-ui/vr-protection.json'
if((Get-FileHash -LiteralPath $Protection -Algorithm SHA256).Hash -ne $Marker.protection_sha256){throw 'VR protection record changed'}
$Protected=Get-Content -LiteralPath $Protection -Raw | ConvertFrom-Json
$Manager=Join-Path $TaskRoot 'tools/vr_launcher_layers.py'
if((Get-FileHash -LiteralPath $Manager -Algorithm SHA256).Hash -ne $Protected.files.'tools/vr_launcher_layers.py'){throw 'Launcher manager changed'}
$Python=Join-Path $Package 'payload/python/python.exe'
$Check=& $Python -B $Manager --root $TaskRoot --validate-active
if($LASTEXITCODE){throw 'Launcher validation failed; nothing was started'}
$State=$Check | ConvertFrom-Json
if(!$Open){$State | ConvertTo-Json;return}
Start-Process -FilePath $State.entry -WorkingDirectory $Package -WindowStyle Normal
