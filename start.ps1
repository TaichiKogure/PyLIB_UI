param([int]$Port = 8765, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$taskArguments = @('main.py', '--port', $Port)
if ($NoBrowser) { $taskArguments += '--no-browser' }
if (Test-Path -LiteralPath $taskPython) {
    & $taskPython @taskArguments
} else {
    py -3 @taskArguments
}
exit $LASTEXITCODE
