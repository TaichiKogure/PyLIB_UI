param([Parameter(Mandatory=$true)][string]$PythonExe)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& $PythonExe -c "import sys; assert sys.version_info[:2] == (3,13), 'Validated runtime is Python 3.13'"
if ($LASTEXITCODE -ne 0) { throw 'Python 3.13 is required for this lock.' }
if (-not (Test-Path -LiteralPath '.venv-research\Scripts\python.exe')) {
    & $PythonExe -m venv .venv-research
    if ($LASTEXITCODE -ne 0) { throw 'Research venv creation failed.' }
}
& '.\.venv-research\Scripts\python.exe' -c "import sys; assert sys.version_info[:2] == (3,13), 'Existing research venv must be Python 3.13'"
if ($LASTEXITCODE -ne 0) { throw 'Existing research venv has a different Python version.' }
& '.\.venv-research\Scripts\python.exe' -m pip install -r requirements-research.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Research dependency installation failed.' }
& '.\.venv-research\Scripts\python.exe' -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Research dependency check failed.' }
