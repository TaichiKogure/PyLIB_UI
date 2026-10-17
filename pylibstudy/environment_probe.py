"""Executed in the research interpreter; only safe structured diagnostics leave it."""
import importlib.metadata
import json
import os
import platform
import sys
from datetime import datetime, timezone

from .capabilities import PINNED_PYBAMM, SUPPORTED_OS, SOLVER

EXPECTED = {'python': [3, 13], 'pybamm': PINNED_PYBAMM, 'solvers': '0.11.1',
            'numpy': '2.3.5', 'casadi': '3.8.1'}


def diagnose():
    os.environ['PYBAMM_DISABLE_TELEMETRY'] = 'true'
    versions = {'python': list(sys.version_info[:2])}
    checks = []
    for key, package in {'pybamm': 'pybamm', 'solvers': 'pybammsolvers', 'numpy': 'numpy', 'casadi': 'casadi'}.items():
        try:
            versions[key] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[key] = None
    for key, expected in EXPECTED.items():
        checks.append(dict(id=key, ok=versions[key] == expected, expected=expected, actual=versions[key]))
    checks.append(dict(id='os', ok=platform.system() in SUPPORTED_OS,
                       expected=list(SUPPORTED_OS), actual=platform.system()))
    runtime_ok = False
    try:
        import pybamm
        import pybammsolvers
        import numpy
        import casadi
        pybamm.IDAKLUSolver(options={'num_threads': 1})
        runtime_ok = pybamm.__version__ == PINNED_PYBAMM
    except Exception:
        pass
    checks.append(dict(id='runtime_imports', ok=runtime_ok,
                       expected='PyBaMM・依存ライブラリ読込とIDAKLU構築', actual='成功' if runtime_ok else '失敗'))
    available = all(c['ok'] for c in checks)
    return dict(available=available, versions=versions, checks=checks,
                solver=SOLVER, checked_at=datetime.now(timezone.utc).isoformat(),
                message='固定計算環境とソルバ読込を確認しました。' if available else
                '固定環境の診断に不一致があります。setup-research.ps1と診断項目を確認してください。',
                scope='版・依存読込・ソルバ構築の診断。計算成功や対象セルの物理精度の検証は含みません。')


if __name__ == '__main__':
    print(json.dumps(diagnose(), ensure_ascii=False))
