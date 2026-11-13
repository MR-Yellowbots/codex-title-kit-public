# Run from the repository or extracted release on Windows PowerShell.
[CmdletBinding()]
param(
    [string]$CodexExe,
    [string]$GitHubCliExe = 'gh.exe',
    [switch]$Remove
)
$ErrorActionPreference = 'Stop'
$taskName = 'Codex Title Kit Update'
if ($Remove) {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    return
}

$launcher = (Get-Command py.exe -CommandType Application).Source
$gh = (Get-Command $GitHubCliExe -CommandType Application).Source
if (-not $CodexExe) {
    $CodexExe = & $launcher -3 -X utf8 -c 'import sys; sys.path.insert(0, sys.argv[1]); from codex_adapter import find_codex; print(find_codex())' $PSScriptRoot
    if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve Codex CLI. Pass -CodexExe.' }
}
$CodexExe = (Get-Item -LiteralPath $CodexExe).FullName
if ([IO.Path]::GetExtension($CodexExe) -ine '.exe') { throw 'Specify the native codex.exe.' }
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' }
$marketplaces = & $CodexExe plugin marketplace list --json
if ($LASTEXITCODE -ne 0) { throw 'Cannot read Codex plugin marketplaces.' }
$market = ($marketplaces | ConvertFrom-Json).marketplaces | Where-Object name -eq 'yellowbots-title-kit'
if (-not $market -or $market.marketplaceSource.sourceType -ne 'git') {
    throw 'Install codex-title-kit from its Git marketplace first.'
}
$updater = Join-Path $market.root 'scripts\update.py'
$state = Join-Path $codexHome 'oil-codex-title\updates\state.json'
& $launcher -3 -X utf8 $updater --codex $CodexExe --gh $gh --state $state --check
if ($LASTEXITCODE -ne 0) { throw 'Version check failed. Verify Codex and GitHub access.' }

# Use the logged-in user session so idle input and the notification use the same desktop.
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 30)
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$arguments = '-3 -X utf8 "{0}" --codex "{1}" --gh "{2}" --state "{3}"' -f $updater, $CodexExe, $gh, $state
$action = New-ScheduledTaskAction -Execute $launcher -Argument $arguments
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
