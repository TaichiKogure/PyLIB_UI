$ErrorActionPreference='Stop'
$root=$PSScriptRoot
$python=Join-Path $root '.venv-research\Scripts\python.exe'
if(-not(Test-Path -LiteralPath $python)){throw '先に固定研究環境を作成してください。'}
& $python -m pip install --no-deps --target (Join-Path $root 'vendor\bpx') -r (Join-Path $root 'requirements-bpx.lock.txt')
if($LASTEXITCODE -ne 0){throw 'BPX依存の取得に失敗しました。既存研究環境は変更していません。'}
