param([string]$Python = 'py')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = '1'
Set-Location -LiteralPath $PSScriptRoot
$taskVenv = Join-Path $PSScriptRoot '.venv'
$taskPython = Join-Path $taskVenv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    if ($Python -eq 'py') { & $Python -3 -m venv $taskVenv }
    else { & $Python -m venv $taskVenv }
    if ($LASTEXITCODE -ne 0) { throw 'Instala Python 3.10 o posterior para Windows y vuelve a ejecutar Instalar.ps1.' }
}
& $taskPython -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'Se necesita Python 3.10 o posterior.' }
& $taskPython -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias. Comprueba la conexión a Internet.' }
Write-Host 'Instalación terminada. Abre IniciarAsistente.cmd para configurar el L20, o Iniciar.cmd -Demo para ver la interfaz sin equipo.'
