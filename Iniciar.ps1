param([switch]$Demo, [switch]$NoBrowser, [int]$Port = 58745)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    & (Join-Path $PSScriptRoot 'Instalar.ps1')
    if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Ejecuta Instalar.ps1 para preparar Python.' }
}
$taskArguments = @((Join-Path $PSScriptRoot 'l20.py'), 'web', '--port', $Port)
if ($Demo) { $taskArguments += '--demo' }
if ($NoBrowser) { $taskArguments += '--no-browser' }
& $taskPython @taskArguments
exit $LASTEXITCODE
