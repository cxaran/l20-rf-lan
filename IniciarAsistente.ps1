param([switch]$Demo, [switch]$Replace, [string]$FromFile, [string]$CredentialFile)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    & (Join-Path $PSScriptRoot 'Instalar.ps1')
    if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Ejecuta Instalar.ps1 para preparar Python.' }
}
$taskArguments = @((Join-Path $PSScriptRoot 'l20.py'))
if ($CredentialFile) { $taskArguments += @('--credentials', $CredentialFile) }
$taskArguments += 'setup'
if ($Demo) { $taskArguments += '--demo' }
if ($Replace) { $taskArguments += '--replace' }
if ($FromFile) { $taskArguments += @('--from-file', $FromFile) }
& $taskPython @taskArguments
exit $LASTEXITCODE
