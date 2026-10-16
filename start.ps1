param([ValidateRange(1, 65535)][int]$Port = 8765, [switch]$NoBrowser, [string]$DataDir)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$taskArguments = @('-m', 'pylibstudy.launcher', '--port', $Port)
if ($DataDir) { $taskArguments += @('--data-dir', $DataDir) }
if ($NoBrowser) { $taskArguments += '--no-browser' }
if (Test-Path -LiteralPath $taskPython) {
    & $taskPython @taskArguments
} else {
    & py -3 @taskArguments
}
exit $LASTEXITCODE
