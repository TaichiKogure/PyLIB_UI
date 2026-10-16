"""Persistent serial queue and a killable solver process, independent of HTTP."""
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .physics import PINNED_PYBAMM, validate_request, validate_design

ROOT = Path(__file__).resolve().parents[1]
ACTIVE = {'queued', 'running', 'cancelling'}
TERMINAL = {'completed', 'partial', 'failed', 'cancelled', 'timeout', 'interrupted'}


def now():
    return datetime.now(timezone.utc).isoformat()


class PhysicsJobs:
    def __init__(self, repository, python_exe=None, start=True):
        self.repository = repository
        self.python = Path(python_exe or ROOT / '.venv-research' / 'Scripts' / 'python.exe')
        self.folder = repository.path.parent / 'physics-jobs';
        self.folder.mkdir(parents=True, exist_ok=True)
        self.owner = (self.folder / 'controller.lock').open('a+b')
        self.owner.seek(0, 2)
        if self.owner.tell() == 0: self.owner.write(b'0');self.owner.flush()
        self.owner.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.owner.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.owner.close()
            raise ValueError('同じ保存先の計算サーバーが既に動作しています。先に終了してください。') from None
        self.lock = threading.RLock();
        self.wake = threading.Event();
        self.stopping = threading.Event()
        self.process = None;
        self.current = None
        # Previous work is never silently resumed or marked successful after restart.
        for job in self.repository.jobs():
            if job['status'] in ACTIVE:
                job.update(status='interrupted', finished_at=now(),
                           message='サーバー再起動で中断。条件を復元して新しいジョブとして実行してください。')
                self.repository.put_job(job)
        self.availability = self.probe()
        self.thread = threading.Thread(target=self.loop, daemon=True, name='physics-jobs') if start else None
        if self.thread: self.thread.start()

    def probe(self):
        if not self.python.is_file():
            return dict(available=False,
                        message='別計算環境がありません。setup-research.ps1で固定環境を作成してください。')
        env = self.environment()
        try:
            result = subprocess.run([str(self.python), '-c',
                                     "import importlib.metadata as m,json,sys;print(json.dumps({'python':list(sys.version_info[:2]),'pybamm':m.version('pybamm'),'solvers':m.version('pybammsolvers'),'numpy':m.version('numpy'),'casadi':m.version('casadi')}))"],
                                    capture_output=True, timeout=10, text=True, env=env,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            versions = json.loads(result.stdout)
            valid = versions['python'] == [3, 13] and versions['pybamm'] == PINNED_PYBAMM and versions[
                'solvers'] == '0.11.1' and versions['numpy'] == '2.3.5' and versions['casadi'] == '3.8.1'
            return dict(available=valid, versions=versions,
                        message='固定計算環境を確認しました。' if valid else '固定版と異なる環境です。setup-research.ps1で再現してください。')
        except Exception:
            return dict(available=False, message='計算環境を確認できません。setup-research.ps1の結果を確認してください。')

    def environment(self):
        env = os.environ.copy()
        env.pop('SSLKEYLOGFILE', None)
        env.update(PYBAMM_DISABLE_TELEMETRY='true', PYTHONIOENCODING='utf-8', OMP_NUM_THREADS='1',
                   OPENBLAS_NUM_THREADS='1',
                   MPLCONFIGDIR=str(self.folder / 'matplotlib'), TEMP=str(self.folder), TMP=str(self.folder))
        return env

    def submit(self, data, project_id='default'):
        self.repository.require_project(project_id)
        c = validate_request(data)
        design = self.repository.design(c['design_id'], project_id) if c['design_id'] else None
        validate_design(c, design)
        if not self.availability['available']:
            raise ValueError(self.availability['message'])
        with self.lock:
            if self.stopping.is_set(): raise ValueError('サーバーを終了しています。')
            if sum(j['status'] in ACTIVE for j in self.repository.jobs()) >= 8:
                raise ValueError('待機中・実行中のジョブは合計8件までです。')
            job = dict(id=str(uuid4()), project_id=project_id, created_at=now(), status='queued', input=c,
                       design_snapshot=design, result_id=str(uuid4()), message='実行待ち。結果は完了時に自動保存します。')
            self.repository.put_job(job)
        self.wake.set()
        return job

    def get(self, job_id, project_id):
        if not isinstance(job_id, str): raise ValueError('ジョブIDを確認してください。')
        for j in self.repository.jobs(project_id):
            if j['id'] == job_id: return j
        raise ValueError('同じプロジェクトのジョブが見つかりません。')

    def cancel(self, job_id, project_id):
        with self.lock:
            job = self.get(job_id, project_id)
            if job['status'] == 'queued':
                job.update(status='cancelled', finished_at=now(), message='開始前に取り消しました。')
            elif job['status'] in {'running', 'cancelling'}:
                job.update(status='cancelling', message='取消を受け付けました。計算プロセスを終了しています。')
                if self.current == job_id and self.process and self.process.poll() is None:
                    try:
                        self.process.terminate()
                    except OSError:
                        pass
            self.repository.put_job(job)
        self.wake.set();
        return job

    def loop(self):
        while not self.stopping.is_set():
            job = None
            try:
                with self.lock:
                    pending = [j for j in reversed(self.repository.jobs()) if j['status'] == 'queued']
                    job = pending[0] if pending else None
                    if job:
                        job.update(status='running', started_at=now(), message='モデルを構築・計算しています。')
                        self.repository.put_job(job);
                        self.current = job['id']
                if job:
                    self.execute(job)
                else:
                    self.wake.wait(.5);
                    self.wake.clear()
            except Exception:
                # Keep HTTP responsive; a storage failure must not turn into success.
                if job:
                    try:
                        with self.lock:
                            latest = self.get(job['id'], job['project_id'])
                            if latest['status'] in ACTIVE:
                                latest.update(status='failed', finished_at=now(),
                                              message='ジョブの保存先または実行環境を確認してください。')
                                self.repository.put_job(latest)
                    except Exception:
                        pass
                self.wake.wait(.5);
                self.wake.clear()

    def worker_command(self, request, output):
        return [str(self.python), '-m', 'pylibstudy.physics_worker', '--request', str(request), '--output', str(output)]

    def execute(self, job):
        folder = self.folder / job['id'];
        folder.mkdir(exist_ok=True)
        request = folder / 'request.json';
        output = folder / 'output.json'
        request.write_text(json.dumps(dict(input=job['input'], design_snapshot=job['design_snapshot'],
                                           result_id=job['result_id'], project_id=job['project_id'],
                                           created_at=job['created_at']), ensure_ascii=False), encoding='utf-8')
        reason = None;
        process = None;
        started = time.monotonic()
        try:
            with (folder / 'worker.log').open('wb') as log:
                with self.lock:
                    process = subprocess.Popen(self.worker_command(request, output),
                                               cwd=ROOT, env=self.environment(), stdout=log, stderr=log,
                                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    self.process = process
                while process.poll() is None:
                    with self.lock:
                        status = self.get(job['id'], job['project_id'])['status']
                    if self.stopping.is_set():
                        reason = 'interrupted'
                    elif status == 'cancelling':
                        reason = 'cancelled'
                    elif time.monotonic() - started > job['input']['timeout_s']:
                        reason = 'timeout'
                    if reason:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill();
                            process.wait(timeout=5)
                        break
                    self.wake.wait(.1);
                    self.wake.clear()
                with self.lock:
                    latest = self.get(job['id'], job['project_id'])
                    if self.stopping.is_set():
                        reason = 'interrupted'
                    elif latest['status'] == 'cancelling':
                        reason = 'cancelled'
                    elif time.monotonic() - started > job['input']['timeout_s']:
                        reason = 'timeout'
                    if reason:
                        messages = dict(cancelled='ユーザー取消。確定結果はありません。',
                                        timeout='実時間上限で停止。確定結果はありません。',
                                        interrupted='サーバー終了で中断。再実行が必要です。')
                        latest.update(status=reason, message=messages[reason])
                    else:
                        payload = json.loads(output.read_text(encoding='utf-8')) if output.is_file() else {}
                        if process.returncode != 0 or not payload.get('ok'):
                            latest.update(status='failed',
                                          message='ソルバが計算できませんでした。初期状態・終止条件・材料と数値条件を確認してください。',
                                          error_code=payload.get('error_code', 'worker_failed'),
                                          error_type=payload.get('error_type', 'ProcessError'))
                            if payload.get('error_code') == 'initial_condition_infeasible':
                                latest['message'] = '初期状態でステップの終止条件に達しています。SOC・電流方向・終止条件を確認してください。'
                        else:
                            result = payload['result']
                            if result['id'] != job['result_id'] or result['project_id'] != job['project_id']:
                                raise ValueError('worker_identity_mismatch')
                            self.repository.save(result)
                            latest.update(status='partial' if result['termination'] == 'partial' else 'completed',
                                          message='一部の計算結果を保存しました。終了理由を確認してください。' if result[
                                                                                                                    'termination'] == 'partial' else 'プロトコル終了。結果を自動保存しました。')
                    latest.update(finished_at=now(), elapsed_s=time.monotonic() - started)
                    self.repository.put_job(latest)
        except Exception:
            with self.lock:
                latest = self.get(job['id'], job['project_id'])
                if latest['status'] not in TERMINAL:
                    latest.update(status='interrupted' if self.stopping.is_set() else 'failed', finished_at=now(),
                                  message='ジョブを完了できませんでした。保存先と計算環境を確認してください。')
                    self.repository.put_job(latest)
        finally:
            if process and process.poll() is None:
                process.kill();
                process.wait(timeout=5)
            with self.lock:
                self.process = None;
                self.current = None

    def close(self):
        if self.owner.closed: return
        self.stopping.set();
        self.wake.set()
        with self.lock:
            if self.process and self.process.poll() is None:
                try:
                    self.process.terminate()
                except OSError:
                    pass
        if self.thread: self.thread.join(timeout=12)
        with self.lock:
            for job in self.repository.jobs():
                if job['status'] in ACTIVE:
                    job.update(status='interrupted', finished_at=now(),
                               message='サーバー終了で中断。条件を復元して再実行してください。')
                    self.repository.put_job(job)
        self.owner.close()
