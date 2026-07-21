#!/usr/bin/env python3
"""Local process manager for the Robots Cluster Scheduler project.

The manager deliberately owns only processes that it starts.  It records their
root PIDs in ``manager/runtime/state.json``, writes all output to rotating log
files, and refuses to overwrite a port held by an unknown process.

Run ``python manager.py --help`` for the command-line interface.  Running the
script without a command starts the Tkinter desktop application.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RUNTIME_DIR = HERE / 'runtime'
LOG_DIR = RUNTIME_DIR / 'logs'
STATE_FILE = RUNTIME_DIR / 'state.json'
CONFIG_FILE = HERE / 'manager_config.json'

BG = '#0b1120'
PANEL = '#111a2e'
PANEL_ALT = '#16223b'
LINE = '#22304d'
TEXT = '#e6edf7'
MUTED = '#8aa0c0'
GREEN = '#34d399'
RED = '#f87171'
YELLOW = '#fbbf24'
GRAY = '#94a3b8'
ACCENT = '#38bdf8'


DEFAULT_CONFIG: dict[str, Any] = {
    'schema_version': 2,
    'python': sys.executable,
    'pnpm': 'pnpm',
    'runtime': {
        'log_max_bytes': 5 * 1024 * 1024,
        'log_backups': 5,
        'health_timeout_seconds': 45,
    },
    'services': {
        'infra': {
            'name': '基础设施 (Postgres / Redis)',
            'mode': 'compose',
            'start_cmd': ['docker', 'compose', '--env-file', 'backend/.env', 'up', '-d', '--wait', '--wait-timeout', '90', 'postgres', 'redis'],
            'stop_cmd': ['docker', 'compose', '--env-file', 'backend/.env', 'stop', '--timeout', '30', 'postgres', 'redis'],
            'cwd': '{root}',
            'color': '#f59e0b',
            'hint': '本机 Docker 容器；不会停止 compose 中其他服务。',
            'ensure_engine': True,
            'docker_desktop': r'C:\Program Files\Docker\Docker\Docker Desktop.exe',
            'auto_start_engine': True,
            'engine_wait_seconds': 120,
        },
        'backend': {
            'name': '后端 API (FastAPI)',
            'mode': 'process',
            'prepare_cmd': ['{python}', '-m', 'alembic', 'upgrade', 'head'],
            'cmd': [
                '{python}', '-m', 'uvicorn', 'app.main:app', '--host',
                '127.0.0.1', '--port', '8000',
            ],
            'cwd': '{root}/backend',
            'port': 8000,
            'url': 'http://127.0.0.1:8000/docs',
            'health_urls': [
                'http://127.0.0.1:8000/ready',
                'http://127.0.0.1:8000/api/auth/setup-status',
            ],
            'color': '#38bdf8',
            'hint': '启动前自动执行数据库迁移；默认不启用 reload。',
        },
        'frontend_pm': {
            'name': '前端 PM 端 (施工进度指挥)',
            'mode': 'process',
            'cmd': [
                'cmd', '/d', '/c', '{pnpm}', '--filter', '@robots/pm', 'exec',
                'vite', '--host', '127.0.0.1', '--port', '5173',
            ],
            'cwd': '{root}/frontend',
            'port': 5173,
            'url': 'http://127.0.0.1:5173',
            'health_urls': ['http://127.0.0.1:5173'],
            'color': '#a78bfa',
            'hint': 'Vite 开发服务，仅监听本机回环地址。',
        },
        'frontend_om': {
            'name': '前端 O&M 端 (设备集群调度)',
            'mode': 'process',
            'cmd': [
                'cmd', '/d', '/c', '{pnpm}', '--filter', '@robots/om', 'exec',
                'vite', '--host', '127.0.0.1', '--port', '5174',
            ],
            'cwd': '{root}/frontend',
            'port': 5174,
            'url': 'http://127.0.0.1:5174',
            'health_urls': ['http://127.0.0.1:5174'],
            'color': '#f472b6',
            'hint': 'Vite 开发服务，仅监听本机回环地址。',
        },
    },
}


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp suitable for state files."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def iso_to_epoch(value: str | None) -> float | None:
    """Convert a persisted ISO timestamp to a local uptime baseline."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def read_dotenv(path: Path) -> dict[str, str]:
    """Read simple dotenv assignments without evaluating their contents."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        line = raw_line.strip()
        if line and not line.startswith('#') and '=' in line:
            name, value = line.split('=', 1)
            values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def local_secret_invalid(value: str) -> bool:
    normalized = value.lower()
    return (
        len(value) < 24
        or normalized.startswith('replace-with-')
        or normalized in {'changeme', 'change-me', 'password', 'secret'}
        or normalized.startswith('<')
    )


def local_secret_errors(path: Path) -> list[str]:
    """Return local backend secret problems without exposing secret values."""
    values = read_dotenv(path)
    errors: list[str] = []
    names = ('JWT_SECRET', 'DEVICE_GATEWAY_API_KEY', 'INITIAL_SETUP_TOKEN')
    for name in names:
        value = values.get(name, '')
        if local_secret_invalid(value):
            errors.append(f'{name} is missing, weak, or still a placeholder.')
    configured = [values.get(name, '') for name in names]
    if len(set(configured)) != len(configured):
        errors.append('JWT, gateway, and setup secrets must all be different.')
    return errors


def initialize_local_env(path: Path) -> bool:
    """Replace only invalid local security placeholders with random values."""
    existing = path.read_text(encoding='utf-8') if path.exists() else ''
    values = read_dotenv(path)
    names = ('JWT_SECRET', 'DEVICE_GATEWAY_API_KEY', 'INITIAL_SETUP_TOKEN')
    if not local_secret_errors(path):
        return False
    invalid_names = {name for name in names if local_secret_invalid(values.get(name, ''))}
    seen_values: set[str] = set()
    for name in names:
        value = values.get(name, '')
        if value in seen_values:
            invalid_names.add(name)
        seen_values.add(value)
    generated = {
        'JWT_SECRET': lambda: secrets.token_urlsafe(48),
        'DEVICE_GATEWAY_API_KEY': lambda: secrets.token_urlsafe(48),
        'INITIAL_SETUP_TOKEN': lambda: secrets.token_urlsafe(32),
    }
    replacements = {name: generated[name]() for name in invalid_names}
    output: list[str] = []
    replaced: set[str] = set()
    for raw_line in existing.splitlines():
        stripped = raw_line.strip()
        if stripped and not stripped.startswith('#') and '=' in stripped:
            name = stripped.split('=', 1)[0].strip()
            if name in replacements:
                output.append(f'{name}={replacements[name]}')
                replaced.add(name)
                continue
        output.append(raw_line)
    if output and output[-1] != '':
        output.append('')
    for name in invalid_names:
        if name not in replaced:
            output.append(f'{name}={replacements[name]}')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(output).rstrip() + '\n', encoding='utf-8')
    return True


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge user configuration without mutating the packaged defaults."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def write_json(path: Path, data: dict[str, Any]) -> None:
    """Atomically persist a small JSON document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + '.tmp')
    temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp_path.replace(path)


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load configuration and migrate the original manager configuration once."""
    config_path = path or CONFIG_FILE
    if not config_path.exists():
        write_json(config_path, DEFAULT_CONFIG)
        return deep_merge({}, DEFAULT_CONFIG)

    raw = json.loads(config_path.read_text(encoding='utf-8'))
    if raw.get('schema_version', 1) < 2:
        # The old tool used --reload and unpinned Vite ports.  Preserve only
        # executable overrides while replacing unsafe service definitions.
        migrated = deep_merge({}, DEFAULT_CONFIG)
        for key in ('python', 'pnpm'):
            if raw.get(key):
                migrated[key] = raw[key]
        write_json(config_path, migrated)
        return migrated
    return deep_merge(DEFAULT_CONFIG, raw)


def pnpm_executable(config: dict[str, Any]) -> str:
    """Resolve pnpm.cmd on Windows, where a PowerShell shim is not executable."""
    configured = str(config['pnpm'])
    if os.name == 'nt' and not configured.lower().endswith(('.cmd', '.exe', '.bat')):
        return shutil.which(configured + '.cmd') or configured + '.cmd'
    return configured


def resolve(value: Any, config: dict[str, Any]) -> Any:
    """Resolve project placeholders in a service configuration value."""
    context = {
        'root': str(ROOT),
        'python': str(config['python']),
        'pnpm': pnpm_executable(config),
    }
    if isinstance(value, list):
        return [resolve(item, config) for item in value]
    if isinstance(value, str):
        for key, replacement in context.items():
            value = value.replace('{' + key + '}', replacement)
    return value


def process_alive(pid: int | None) -> bool:
    """Return whether the supplied process identifier still exists."""
    if not pid:
        return False
    if os.name == 'nt':
        completed = subprocess.run(
            ['tasklist', '/FI', f'PID eq {pid}', '/NH'],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in completed.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def listening_pid(port: int) -> int | None:
    """Look up the PID listening on a TCP port without adding psutil."""
    if os.name == 'nt':
        command = (
            f"$items = Get-NetTCPConnection -State Listen -LocalPort {port} "
            "-ErrorAction SilentlyContinue; "
            "$items | ForEach-Object { $_.OwningProcess }"
        )
        completed = subprocess.run(
            ['powershell.exe', '-NoProfile', '-Command', command],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in completed.stdout.splitlines():
            if line.strip().isdigit():
                return int(line.strip())
        return None
    completed = subprocess.run(
        ['lsof', '-nP', f'-iTCP:{port}', '-sTCP:LISTEN', '-t'],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in completed.stdout.splitlines():
        if line.strip().isdigit():
            return int(line.strip())
    return None


def process_info(pid: int | None) -> dict[str, str] | None:
    """Read a process fingerprint used to prevent PID-reuse termination."""
    if not pid:
        return None
    if os.name == 'nt':
        command = (
            f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'; "
            "if ($p) { [PSCustomObject]@{Name=$p.Name; ExecutablePath=$p.ExecutablePath; "
            "CommandLine=$p.CommandLine; CreationDate=$p.CreationDate.ToUniversalTime().ToString('o')} "
            '| ConvertTo-Json -Compress }'
        )
        completed = subprocess.run(
            ['powershell.exe', '-NoProfile', '-Command', command],
            capture_output=True,
            text=True,
            check=False,
        )
        try:
            decoded = json.loads(completed.stdout)
            return {key: str(decoded.get(key) or '') for key in ('Name', 'ExecutablePath', 'CommandLine', 'CreationDate')}
        except (json.JSONDecodeError, TypeError):
            return None
    proc_path = Path('/proc') / str(pid)
    try:
        return {
            'Name': (proc_path / 'comm').read_text(encoding='utf-8').strip(),
            'ExecutablePath': os.readlink(proc_path / 'exe'),
            'CommandLine': (proc_path / 'cmdline').read_bytes().replace(b'\0', b' ').decode('utf-8', 'replace').strip(),
            'CreationDate': str((proc_path / 'stat').stat().st_ctime_ns),
        }
    except OSError:
        return None


def process_details(pid: int | None) -> str:
    """Return a compact human-readable process description."""
    info = process_info(pid)
    if info:
        return f"PID {pid} | {info.get('Name', 'unknown')} | {info.get('CommandLine', '')}"
    return f'PID {pid}'


def process_matches_record(record: dict[str, Any]) -> bool:
    """Confirm PID, creation time, executable, and command before ownership use."""
    fingerprint = record.get('fingerprint')
    current = process_info(record.get('pid'))
    if not isinstance(fingerprint, dict) or not current:
        return False
    return all(current.get(key, '') == str(fingerprint.get(key, '')) for key in ('Name', 'ExecutablePath', 'CommandLine', 'CreationDate'))


def terminate_process_tree(pid: int, graceful_timeout: int = 15) -> tuple[bool, str]:
    """Request graceful process-tree shutdown, then force only as a fallback."""
    try:
        if os.name == 'nt':
            completed = subprocess.run(
                ['taskkill', '/T', '/PID', str(pid)],
                capture_output=True,
                text=True,
                check=False,
            )
            deadline = time.monotonic() + graceful_timeout
            while process_alive(pid) and time.monotonic() < deadline:
                time.sleep(0.25)
            if not process_alive(pid):
                return True, (completed.stdout or 'Process tree stopped gracefully.').strip()
            forced = subprocess.run(
                ['taskkill', '/F', '/T', '/PID', str(pid)],
                capture_output=True,
                text=True,
                check=False,
            )
            text = (forced.stdout or forced.stderr).strip()
            return forced.returncode == 0 and not process_alive(pid), f'Graceful timeout; forced termination. {text}'
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        deadline = time.monotonic() + graceful_timeout
        while process_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.25)
        if process_alive(pid):
            os.killpg(os.getpgid(pid), signal.SIGKILL)
            return not process_alive(pid), f'Graceful timeout; forced process group {pid} to stop.'
        return True, f'Process group {pid} stopped gracefully.'
    except Exception as exc:  # pragma: no cover - platform/process dependent
        return False, str(exc)


def http_ok(url: str, timeout: float = 3.0) -> bool:
    """Check a local HTTP endpoint without leaking response contents."""
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'robots-manager/1.0'})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 400
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


@dataclass
class Service:
    """Runtime state for one configured service."""

    key: str
    config: dict[str, Any]
    process: subprocess.Popen[bytes] | None = None
    status: str = 'stopped'
    health: str = 'unknown'
    detail: str = ''
    pid: int | None = None
    started_at: float | None = None
    stopping: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def port(self) -> int | None:
        value = self.config.get('port')
        return int(value) if value is not None else None


class ProcessManager:
    """Own project service processes, persistent logs, and health checks."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.services = {
            key: Service(key, service_config)
            for key, service_config in config['services'].items()
        }
        self.log_buffer: deque[dict[str, str]] = deque(maxlen=5000)
        self.log_queue: queue.Queue[dict[str, str]] = queue.Queue()
        self._log_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._cancel_start = threading.Event()
        self._tail_offsets: dict[str, int] = {}
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._state = self._read_state()
        self._reap_stale_state()
        self.load_log_history()

    def _read_state(self) -> dict[str, Any]:
        if not STATE_FILE.exists():
            return {'version': 1, 'services': {}}
        try:
            payload = json.loads(STATE_FILE.read_text(encoding='utf-8'))
            if isinstance(payload.get('services'), dict):
                return payload
        except (OSError, json.JSONDecodeError):
            pass
        return {'version': 1, 'services': {}}

    def _save_state(self) -> None:
        with self._state_lock:
            write_json(STATE_FILE, self._state)

    def _reap_stale_state(self) -> None:
        changed = False
        for key, record in list(self._state.get('services', {}).items()):
            if record.get('mode') == 'process' and not process_matches_record(record):
                del self._state['services'][key]
                changed = True
        if changed:
            self._save_state()

    def _record(self, key: str) -> dict[str, Any] | None:
        return self._state.get('services', {}).get(key)

    def _set_record(self, key: str, record: dict[str, Any]) -> None:
        self._state.setdefault('services', {})[key] = record
        self._save_state()

    def _clear_record(self, key: str) -> None:
        if key in self._state.get('services', {}):
            del self._state['services'][key]
            self._save_state()

    def log_path(self, key: str) -> Path:
        return LOG_DIR / f'{key}.log'

    def _rotate_log_if_needed(self, key: str) -> None:
        path = self.log_path(key)
        max_bytes = int(self.config['runtime']['log_max_bytes'])
        backups = int(self.config['runtime']['log_backups'])
        if not path.exists() or path.stat().st_size < max_bytes:
            return
        for index in range(backups - 1, 0, -1):
            source = path.with_suffix(f'.log.{index}')
            destination = path.with_suffix(f'.log.{index + 1}')
            if source.exists():
                source.replace(destination)
        if path.exists():
            path.replace(path.with_suffix('.log.1'))

    def push_log(self, key: str, stream: str, text: str) -> None:
        """Add a manager event to the UI queue and durable service log."""
        clean_text = text.rstrip('\r\n')
        if not clean_text:
            return
        timestamp = datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')
        record = {'ts': timestamp, 'service': key, 'stream': stream, 'text': clean_text}
        with self._log_lock:
            with self.log_path(key).open('a', encoding='utf-8') as log_file:
                log_file.write(f'[{timestamp}] [{stream}] {clean_text}\n')
        self.log_buffer.append(record)
        self.log_queue.put(record)

    def load_log_history(self, per_service: int = 400) -> None:
        """Load the recent durable logs so a restarted GUI retains context."""
        for key in self.services:
            path = self.log_path(key)
            if not path.exists():
                self._tail_offsets[key] = 0
                continue
            try:
                lines = path.read_text(encoding='utf-8', errors='replace').splitlines()[-per_service:]
                for line in lines:
                    self.log_buffer.append({
                        'ts': datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S'),
                        'service': key,
                        'stream': 'stdout',
                        'text': line,
                    })
                self._tail_offsets[key] = path.stat().st_size
            except OSError:
                self._tail_offsets[key] = 0

    def poll_log_files(self) -> None:
        """Tail durable logs, including output written by child processes."""
        for key in self.services:
            path = self.log_path(key)
            if not path.exists():
                continue
            try:
                size = path.stat().st_size
                offset = self._tail_offsets.get(key, 0)
                if size < offset:
                    offset = 0
                if size == offset:
                    continue
                with path.open('r', encoding='utf-8', errors='replace') as log_file:
                    log_file.seek(offset)
                    lines = log_file.readlines()
                    self._tail_offsets[key] = log_file.tell()
                for line in lines:
                    text = line.rstrip('\r\n')
                    if text:
                        record = {
                            'ts': datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S'),
                            'service': key,
                            'stream': 'stdout',
                            'text': text,
                        }
                        self.log_buffer.append(record)
                        self.log_queue.put(record)
            except OSError:
                continue

    def port_occupant(self, service: Service) -> int | None:
        return listening_pid(service.port) if service.port else None

    def status_for(self, key: str, refresh_health: bool = False) -> tuple[str, int | None, str]:
        """Return status, relevant PID, and a concise diagnostic message."""
        service = self.services[key]
        if service.config.get('mode') == 'compose':
            snapshot = self.compose_snapshot(service)
            if snapshot is None:
                return 'unavailable', None, 'Docker engine or Compose is unavailable.'
            running = self.compose_snapshot_healthy(snapshot)
            any_running = any(str(item.get('State', '')).lower() == 'running' for item in snapshot.values())
            record = self._record(key)
            expected = record.get('containers') if record else None
            owned = isinstance(expected, dict) and all(
                snapshot.get(name, {}).get('ID') == container_id
                for name, container_id in expected.items()
            )
            if running and owned:
                return 'running', None, 'Docker containers are running.'
            if running or any_running:
                if record:
                    self._clear_record(key)
                return 'external', None, 'Docker containers were not started by this manager.'
            if record:
                self._clear_record(key)
            return 'stopped', None, ''

        record = self._record(key)
        if record and process_matches_record(record):
            if service.started_at is None:
                service.started_at = iso_to_epoch(record.get('started_at'))
            health = self.check_service_health(service) if refresh_health else service.health
            service.health = health
            detail = 'healthy' if health == 'healthy' else health
            return 'running' if health != 'unhealthy' else 'unhealthy', record.get('pid'), detail
        if record:
            self._clear_record(key)

        occupant = self.port_occupant(service)
        if occupant:
            return 'external', occupant, process_details(occupant)
        return 'stopped', None, ''

    def refresh_service_states(self, refresh_health: bool = False) -> None:
        """Synchronize visible service state with persistent ownership records."""
        for key, service in self.services.items():
            status, pid, detail = self.status_for(key, refresh_health)
            if service.status not in ('starting', 'stopping'):
                service.status = status
                service.detail = detail
                service.pid = pid
                if status == 'unhealthy':
                    service.health = 'unhealthy'
                elif status == 'running':
                    service.health = 'healthy'

    def compose_snapshot(self, service: Service) -> dict[str, dict[str, Any]] | None:
        """Read container IDs, states, health, and exit codes for local infra."""
        command = ['docker', 'compose', '--env-file', 'backend/.env', 'ps', '--all', '--format', 'json']
        try:
            completed = subprocess.run(
                command,
                cwd=resolve(service.config['cwd'], self.config),
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        output = completed.stdout.strip()
        if not output:
            return {}
        items: list[dict[str, Any]] = []
        try:
            decoded = json.loads(output)
            items = decoded if isinstance(decoded, list) else [decoded]
        except json.JSONDecodeError:
            for line in output.splitlines():
                try:
                    decoded = json.loads(line)
                except json.JSONDecodeError:
                    continue
                items.extend(decoded if isinstance(decoded, list) else [decoded])
        return {str(item.get('Service')): item for item in items if item.get('Service')}

    @staticmethod
    def compose_snapshot_healthy(snapshot: dict[str, dict[str, Any]]) -> bool:
        for name in ('postgres', 'redis'):
            item = snapshot.get(name)
            if not item or str(item.get('State', '')).lower() != 'running':
                return False
            health = str(item.get('Health', '')).lower()
            if health and health != 'healthy':
                return False
        return True

    def compose_running(self, service: Service) -> bool:
        snapshot = self.compose_snapshot(service)
        return snapshot is not None and self.compose_snapshot_healthy(snapshot)

    def docker_engine_ok(self) -> bool:
        try:
            completed = subprocess.run(
                ['docker', 'info', '--format', '{{.ServerVersion}}'],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            return completed.returncode == 0 and bool(completed.stdout.strip())
        except (OSError, subprocess.TimeoutExpired):
            return False

    def ensure_docker_engine(self, service: Service) -> bool:
        """Start Docker Desktop only when configured and necessary."""
        if self.docker_engine_ok():
            self.push_log(service.key, 'system', 'Docker engine is ready.')
            return True
        if not service.config.get('auto_start_engine', True):
            self.push_log(service.key, 'stderr', 'Docker engine is unavailable. Start Docker Desktop first.')
            return False
        desktop = Path(str(service.config.get('docker_desktop', '')))
        if not desktop.is_file():
            self.push_log(service.key, 'stderr', 'Docker engine is unavailable and Docker Desktop was not found.')
            return False
        self.push_log(service.key, 'system', 'Starting Docker Desktop and waiting for the engine.')
        try:
            subprocess.Popen([str(desktop)], creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))
        except OSError as exc:
            self.push_log(service.key, 'stderr', f'Unable to start Docker Desktop: {exc}')
            return False
        deadline = time.monotonic() + int(service.config.get('engine_wait_seconds', 120))
        while time.monotonic() < deadline:
            if self.docker_engine_ok():
                self.push_log(service.key, 'system', 'Docker engine is ready.')
                return True
            time.sleep(3)
        self.push_log(service.key, 'stderr', 'Timed out waiting for Docker engine.')
        return False

    def _run_capture(self, service: Service, command: list[str], cwd: str, label: str) -> bool:
        self.push_log(service.key, 'system', f'{label}: ' + ' '.join(command))
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=600,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.push_log(service.key, 'stderr', f'{label} failed: {exc}')
            return False
        for line in completed.stdout.splitlines():
            self.push_log(service.key, 'stdout', line)
        for line in completed.stderr.splitlines():
            self.push_log(service.key, 'stderr', line)
        if completed.returncode:
            self.push_log(service.key, 'stderr', f'{label} exited with code {completed.returncode}.')
            return False
        return True

    def start_service(self, key: str, wait: bool = False) -> None:
        """Start one service asynchronously unless ``wait`` is requested."""
        if key not in self.services:
            raise KeyError(f'Unknown service: {key}')
        def run_one() -> None:
            with self._lifecycle_lock:
                self._cancel_start.clear()
                self._start_worker(key)

        worker = threading.Thread(target=run_one, daemon=True)
        worker.start()
        if wait:
            worker.join()

    def _start_worker(self, key: str) -> None:
        service = self.services[key]
        with service.lock:
            if self._cancel_start.is_set():
                service.status = 'stopped'
                return
            status, pid, detail = self.status_for(key)
            if status in ('running', 'unhealthy'):
                self.push_log(key, 'system', f'Already managed and running (PID={pid or "container"}).')
                service.status = status
                return
            if status == 'external':
                self.push_log(key, 'stderr', f'Refusing to take over an external process: {detail}')
                service.status = 'external'
                service.detail = detail
                return
            service.status = 'starting'
            service.health = 'unknown'
            service.detail = ''
            service.stopping = False
            # The child writes directly to this file so output also survives a
            # manager restart.  Rotate before launching, never while its file
            # handle is active.
            self._rotate_log_if_needed(key)

            if service.config.get('mode') == 'compose':
                self._start_compose(service)
                return
            self._start_process(service)

    def _start_compose(self, service: Service) -> None:
        if service.config.get('ensure_engine') and not self.ensure_docker_engine(service):
            service.status = 'error'
            return
        cwd = str(resolve(service.config['cwd'], self.config))
        command = resolve(service.config['start_cmd'], self.config)
        if not self._run_capture(service, command, cwd, 'Starting infrastructure'):
            service.status = 'error'
            return
        snapshot = self.compose_snapshot(service)
        if snapshot is None or not self.compose_snapshot_healthy(snapshot):
            service.status = 'error'
            self.push_log(service.key, 'stderr', 'Containers did not reach running and healthy states.')
            return
        service.status = 'running'
        service.health = 'healthy'
        service.started_at = time.time()
        self._set_record(service.key, {
            'mode': 'compose',
            'started_at': utc_now(),
            'containers': {name: item.get('ID') for name, item in snapshot.items() if name in {'postgres', 'redis'}},
        })
        self.push_log(service.key, 'system', 'Infrastructure is running.')

    def _start_process(self, service: Service) -> None:
        if service.key == 'backend':
            errors = local_secret_errors(ROOT / 'backend' / '.env')
            if errors:
                service.status = 'error'
                for error in errors:
                    self.push_log(service.key, 'stderr', error)
                self.push_log(service.key, 'stderr', 'Run manager.py init-env, then restart the project.')
                return
        port = service.port
        if port and (occupant := listening_pid(port)):
            service.status = 'external'
            service.detail = process_details(occupant)
            self.push_log(service.key, 'stderr', f'Port {port} is held by {service.detail}')
            return
        cwd = str(resolve(service.config['cwd'], self.config))
        prepare_command = service.config.get('prepare_cmd')
        if prepare_command:
            command = resolve(prepare_command, self.config)
            if not self._run_capture(service, command, cwd, 'Preparing service'):
                service.status = 'error'
                return
        command = resolve(service.config['cmd'], self.config)
        self.push_log(service.key, 'system', 'Starting: ' + ' '.join(command))
        log_file: Any = None
        try:
            log_file = self.log_path(service.key).open('ab', buffering=0)
            kwargs: dict[str, Any] = {
                'cwd': cwd,
                'stdin': subprocess.DEVNULL,
                'stdout': log_file,
                'stderr': subprocess.STDOUT,
            }
            if os.name == 'nt':
                kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
            else:
                kwargs['start_new_session'] = True
            process = subprocess.Popen(command, **kwargs)
        except OSError as exc:
            service.status = 'error'
            self.push_log(service.key, 'stderr', f'Process launch failed: {exc}')
            return
        finally:
            if log_file is not None:
                log_file.close()

        service.process = process
        service.pid = process.pid
        service.status = 'running'
        service.started_at = time.time()
        fingerprint = None
        for _attempt in range(10):
            fingerprint = process_info(process.pid)
            if fingerprint:
                break
            time.sleep(0.05)
        if not fingerprint:
            terminate_process_tree(process.pid)
            service.process = None
            service.pid = None
            service.status = 'error'
            self.push_log(service.key, 'stderr', 'Unable to fingerprint the new process; it was stopped to preserve ownership safety.')
            return
        self._set_record(service.key, {
            'mode': 'process',
            'pid': process.pid,
            'port': port,
            'started_at': utc_now(),
            'command': command,
            'fingerprint': fingerprint,
        })
        self.push_log(service.key, 'system', f'Started managed process tree (PID={process.pid}).')
        threading.Thread(target=self._monitor_process, args=(service, process), daemon=True).start()
        self._wait_for_health(service, process)

    def _monitor_process(self, service: Service, process: subprocess.Popen[bytes]) -> None:
        return_code = process.wait()
        with service.lock:
            if service.process is not process:
                return
            service.process = None
            service.pid = None
            self._clear_record(service.key)
            if service.stopping:
                service.stopping = False
                service.status = 'stopped'
                self.push_log(service.key, 'system', 'Service stopped.')
            else:
                service.status = 'error'
                service.health = 'unhealthy'
                self.push_log(service.key, 'stderr', f'Process exited unexpectedly (code={return_code}).')

    def _wait_for_health(self, service: Service, process: subprocess.Popen[bytes]) -> None:
        endpoints = service.config.get('health_urls', [])
        if not endpoints:
            service.health = 'healthy'
            return
        timeout = int(self.config['runtime']['health_timeout_seconds'])
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._cancel_start.is_set():
                self.push_log(service.key, 'system', 'Health wait cancelled by stop request.')
                return
            if process.poll() is not None:
                return
            if all(http_ok(url) for url in endpoints):
                service.health = 'healthy'
                service.detail = 'Health checks passed.'
                self.push_log(service.key, 'system', 'Health checks passed.')
                return
            time.sleep(1)
        if process.poll() is None:
            service.health = 'unhealthy'
            service.status = 'unhealthy'
            service.detail = 'Health checks timed out; inspect the service log.'
            self.push_log(service.key, 'stderr', service.detail)

    def check_service_health(self, service: Service) -> str:
        endpoints = service.config.get('health_urls', [])
        if not endpoints:
            return 'healthy' if self.compose_running(service) else 'unknown'
        return 'healthy' if all(http_ok(url) for url in endpoints) else 'unhealthy'

    def stop_service(self, key: str, force_external: bool = False, wait: bool = False) -> None:
        """Stop a manager-owned service, never an external process by default."""
        if key not in self.services:
            raise KeyError(f'Unknown service: {key}')
        self._cancel_start.set()

        def run_one() -> None:
            with self._lifecycle_lock:
                self._stop_worker(key, force_external)

        worker = threading.Thread(target=run_one, daemon=True)
        worker.start()
        if wait:
            worker.join()

    def _stop_worker(self, key: str, force_external: bool) -> None:
        service = self.services[key]
        with service.lock:
            status, pid, detail = self.status_for(key)
            if status == 'stopped':
                service.status = 'stopped'
                self.push_log(key, 'system', 'Service is already stopped.')
                return
            if status == 'external' and not force_external:
                service.status = 'external'
                self.push_log(key, 'stderr', 'External process was not stopped. Use the explicit force action to stop it.')
                return
            if key == 'infra':
                backend_status, _backend_pid, _backend_detail = self.status_for('backend')
                if backend_status in ('running', 'unhealthy'):
                    service.status = status
                    self.push_log(key, 'stderr', 'Refusing to stop infrastructure while the backend is running. Stop backend first.')
                    return
            service.status = 'stopping'
            service.stopping = True
            if service.config.get('mode') == 'compose':
                self._stop_compose(service, force_external)
                return
            if not pid:
                service.status = 'error'
                self.push_log(key, 'stderr', 'No PID was available for the process to stop.')
                return
            self.push_log(key, 'system', f'Stopping process tree (PID={pid}).')
            success, message = terminate_process_tree(pid)
            self.push_log(key, 'system' if success else 'stderr', message)
            if success:
                self._clear_record(key)
                service.process = None
                service.pid = None
                service.status = 'stopped'
                service.health = 'unknown'
                service.stopping = False
            else:
                service.status = 'error'

    def _stop_compose(self, service: Service, force_external: bool) -> None:
        if not self._record(service.key) and not force_external:
            service.status = 'external'
            self.push_log(service.key, 'stderr', 'Infrastructure was not started by this manager.')
            return
        cwd = str(resolve(service.config['cwd'], self.config))
        command = resolve(service.config['stop_cmd'], self.config)
        if self._run_capture(service, command, cwd, 'Stopping infrastructure'):
            snapshot = self.compose_snapshot(service) or {}
            self._clear_record(service.key)
            forced = [name for name, item in snapshot.items() if str(item.get('ExitCode', '')) == '137']
            service.status = 'error' if forced else 'stopped'
            service.health = 'unknown'
            service.stopping = False
            if forced:
                self.push_log(service.key, 'stderr', 'Infrastructure stopped with exit code 137: ' + ', '.join(forced))
            else:
                self.push_log(service.key, 'system', 'Infrastructure stopped gracefully.')
        else:
            service.status = 'error'

    def start_all(self, wait: bool = False) -> None:
        """Start infra, API, and both frontends in dependency order."""
        def worker() -> None:
            with self._lifecycle_lock:
                self._cancel_start.clear()
                for key in ('infra', 'backend', 'frontend_pm', 'frontend_om'):
                    if self._cancel_start.is_set():
                        break
                    if key in self.services:
                        self._start_worker(key)
                        status, _pid, _detail = self.status_for(key, refresh_health=True)
                        if status != 'running':
                            self.push_log(key, 'stderr', 'Project startup stopped because this dependency is not healthy.')
                            break

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        if wait:
            thread.join()

    def stop_all(self, wait: bool = False) -> None:
        """Stop only services whose state file marks them as manager-owned."""
        self._cancel_start.set()

        def worker() -> None:
            with self._lifecycle_lock:
                for key in ('frontend_om', 'frontend_pm', 'backend', 'infra'):
                    if key in self.services:
                        self._stop_worker(key, False)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        if wait:
            thread.join()

    def status_rows(self, refresh_health: bool = True) -> list[tuple[str, str, str, str]]:
        """Return portable CLI status rows for configured services."""
        rows: list[tuple[str, str, str, str]] = []
        for key, service in self.services.items():
            status, pid, detail = self.status_for(key, refresh_health)
            rows.append((key, status, str(pid or '-'), detail))
        return rows

    def doctor(self) -> tuple[bool, list[str]]:
        """Run non-mutating local prerequisite checks without printing secrets."""
        lines: list[str] = []
        healthy = True
        python_path = Path(str(resolve('{python}', self.config)))
        if python_path.is_file():
            lines.append(f'OK   Python: {python_path}')
        else:
            healthy = False
            lines.append(f'FAIL Python executable not found: {python_path}')
        try:
            pnpm = subprocess.run(
                [pnpm_executable(self.config), '--version'],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if pnpm.returncode == 0:
                lines.append(f'OK   pnpm: {pnpm.stdout.strip()}')
            else:
                healthy = False
                lines.append('FAIL pnpm is unavailable.')
        except (OSError, subprocess.TimeoutExpired):
            healthy = False
            lines.append('FAIL pnpm is unavailable.')
        lines.append('OK   Docker engine available.' if self.docker_engine_ok() else 'WARN Docker engine is unavailable.')

        env_path = ROOT / 'backend' / '.env'
        if not env_path.exists():
            healthy = False
            lines.append('FAIL backend/.env is missing.')
        secret_errors = local_secret_errors(env_path)
        if secret_errors:
            healthy = False
            lines.extend(f'FAIL {error}' for error in secret_errors)
        else:
            lines.append('OK   Local JWT, gateway, and setup secrets are non-placeholder and distinct.')

        for key, service in self.services.items():
            if service.port:
                occupant = self.port_occupant(service)
                if occupant:
                    lines.append(f'INFO {key} port {service.port} is occupied by PID {occupant}.')
                else:
                    lines.append(f'OK   {key} port {service.port} is available.')
        return healthy, lines


def format_status(rows: list[tuple[str, str, str, str]]) -> str:
    """Format status rows without requiring a third-party table library."""
    headers = ('SERVICE', 'STATUS', 'PID', 'DETAIL')
    widths = [len(value) for value in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))
    output = ['  '.join(headers[index].ljust(widths[index]) for index in range(len(headers)))]
    output.append('  '.join('-' * width for width in widths))
    for row in rows:
        output.append('  '.join(row[index].ljust(widths[index]) for index in range(len(row))))
    return '\n'.join(output)


def cli_logs(manager: ProcessManager, key: str, tail: int, follow: bool) -> int:
    """Print a durable service log and optionally tail it until interrupted."""
    if key not in manager.services:
        print(f'Unknown service: {key}', file=sys.stderr)
        return 2
    path = manager.log_path(key)
    if not path.exists():
        print(f'No log has been written for {key}.')
        return 0
    with path.open('r', encoding='utf-8', errors='replace') as log_file:
        lines = log_file.readlines()
        for line in lines[-tail:]:
            write_console(line)
        if not follow:
            return 0
        offset = log_file.tell()
    try:
        while True:
            time.sleep(0.5)
            if not path.exists():
                continue
            with path.open('r', encoding='utf-8', errors='replace') as log_file:
                if path.stat().st_size < offset:
                    offset = 0
                log_file.seek(offset)
                chunk = log_file.read()
                offset = log_file.tell()
            if chunk:
                write_console(chunk, flush=True)
    except KeyboardInterrupt:
        return 0


def write_console(text: str, flush: bool = False) -> None:
    """Write logs even when the Windows console uses a legacy code page."""
    try:
        sys.stdout.write(text)
        if flush:
            sys.stdout.flush()
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or 'utf-8'
        rendered = text.encode(encoding, errors='backslashreplace')
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout.buffer.write(rendered)
            if flush:
                sys.stdout.buffer.flush()
        else:  # pragma: no cover - stdout normally exposes a binary buffer
            sys.stdout.write(rendered.decode(encoding, errors='replace'))


class ManagerApp:
    """Desktop front-end for the same ProcessManager used by the CLI."""

    def __init__(self, root: tk.Tk, manager: ProcessManager) -> None:
        self.root = root
        self.manager = manager
        self.cards: dict[str, dict[str, tk.Widget]] = {}
        self.filter_var = tk.StringVar(value='全部')
        self.autoscroll_var = tk.BooleanVar(value=True)
        self._last_health_refresh = 0.0
        self._refresh_in_progress = False
        root.title('机器人集群调度系统 - 服务管理器')
        root.geometry('1100x760')
        root.minsize(900, 620)
        root.configure(bg=BG)
        self._build_topbar()
        self._build_cards()
        self._build_log_panel()
        root.protocol('WM_DELETE_WINDOW', self._on_close)
        self.render_history()
        self._poll()

    def _build_topbar(self) -> None:
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill='x', padx=14, pady=12)
        title = tk.Frame(bar, bg=BG)
        title.pack(side='left')
        tk.Label(title, text='机器人集群调度系统 - 服务管理器', font=('Microsoft YaHei', 15, 'bold'), fg=TEXT, bg=BG).pack(anchor='w')
        tk.Label(title, text='仅管理由本工具启动的服务；日志保存在 manager/runtime/logs', font=('Microsoft YaHei', 9), fg=MUTED, bg=BG).pack(anchor='w')
        actions = tk.Frame(bar, bg=BG)
        actions.pack(side='right')
        self._button(actions, '启动项目', lambda: self.manager.start_all(), '#0ea5e9', 'white').pack(side='left', padx=3)
        self._button(actions, '停止已管理服务', self._stop_all, '#3a1620', '#fecaca').pack(side='left', padx=3)
        self._button(actions, '刷新状态', self._refresh, PANEL_ALT, TEXT).pack(side='left', padx=3)

    def _build_cards(self) -> None:
        container = tk.Frame(self.root, bg=BG)
        container.pack(fill='x', padx=14, pady=(0, 10))
        for index, (key, service) in enumerate(self.manager.services.items()):
            card = tk.Frame(container, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
            card.grid(row=index // 2, column=index % 2, sticky='nsew', padx=5, pady=5)
            container.grid_columnconfigure(index % 2, weight=1)
            color = service.config.get('color', ACCENT)
            tk.Frame(card, bg=color, width=4).pack(side='left', fill='y')
            body = tk.Frame(card, bg=PANEL)
            body.pack(side='left', fill='both', expand=True, padx=12, pady=10)
            tk.Label(body, text=service.config['name'], font=('Microsoft YaHei', 11, 'bold'), fg=TEXT, bg=PANEL).pack(anchor='w')
            tk.Label(body, text=service.config.get('hint', ''), font=('Microsoft YaHei', 9), fg=MUTED, bg=PANEL, wraplength=420, justify='left').pack(anchor='w', pady=(2, 0))
            status = tk.Label(body, text='● 已停止', font=('Microsoft YaHei', 10), fg=GRAY, bg='#1c2536', padx=8, pady=2)
            status.pack(anchor='w', pady=(8, 0))
            meta = tk.Label(body, text='PID: -   状态: -', font=('Consolas', 9), fg=MUTED, bg=PANEL, anchor='w')
            meta.pack(anchor='w', pady=(5, 0))
            actions = tk.Frame(body, bg=PANEL)
            actions.pack(anchor='w', pady=(8, 0))
            start = self._button(actions, '启动', lambda value=key: self.manager.start_service(value), '#0ea5e9', 'white')
            start.pack(side='left', padx=(0, 5))
            stop = self._button(actions, '停止', lambda value=key: self.manager.stop_service(value), '#3a1620', '#fecaca')
            stop.pack(side='left', padx=(0, 5))
            inspect = self._button(actions, '查看占用', lambda value=key: self._inspect(value), PANEL_ALT, TEXT)
            inspect.pack(side='left', padx=(0, 5))
            if service.config.get('url'):
                self._button(actions, '打开', lambda value=service.config['url']: webbrowser.open(value), PANEL_ALT, ACCENT).pack(side='left')
            self.cards[key] = {'status': status, 'meta': meta, 'start': start, 'stop': stop}

    @staticmethod
    def _button(parent: tk.Widget, text: str, command: Callable[[], None], bg: str, fg: str) -> tk.Button:
        return tk.Button(parent, text=text, command=command, bg=bg, fg=fg, relief='flat', font=('Microsoft YaHei', 9), padx=9, pady=4)

    def _build_log_panel(self) -> None:
        panel = tk.LabelFrame(self.root, text=' 日志输出 ', font=('Microsoft YaHei', 11), fg=TEXT, bg=BG, highlightbackground=LINE, highlightthickness=1)
        panel.pack(fill='both', expand=True, padx=14, pady=(0, 14))
        toolbar = tk.Frame(panel, bg=BG)
        toolbar.pack(fill='x', padx=10, pady=(6, 4))
        tk.Label(toolbar, text='服务:', fg=MUTED, bg=BG, font=('Microsoft YaHei', 9)).pack(side='left')
        selector = ttk.Combobox(toolbar, textvariable=self.filter_var, values=['全部', *self.manager.services.keys()], state='readonly', width=14)
        selector.pack(side='left', padx=(4, 10))
        selector.bind('<<ComboboxSelected>>', lambda _: self.render_history())
        tk.Checkbutton(toolbar, text='自动滚动', variable=self.autoscroll_var, fg=MUTED, bg=BG, selectcolor=PANEL_ALT, activebackground=BG, font=('Microsoft YaHei', 9)).pack(side='left')
        self._button(toolbar, '清除显示', self.render_empty, PANEL_ALT, TEXT).pack(side='right')
        self.log_text = scrolledtext.ScrolledText(panel, bg='#0a0f1c', fg=TEXT, font=('Consolas', 10), relief='flat', state='disabled', wrap='word', insertbackground=TEXT)
        self.log_text.pack(fill='both', expand=True, padx=10, pady=(0, 8))
        for key, service in self.manager.services.items():
            self.log_text.tag_configure(f'svc_{key}', foreground=service.config.get('color', ACCENT))
        self.log_text.tag_configure('stderr', foreground=RED)
        self.log_text.tag_configure('system', foreground=YELLOW)

    def _tag_for(self, record: dict[str, str]) -> str:
        if record['stream'] == 'system':
            return 'system'
        if record['stream'] == 'stderr' or any(word in record['text'].lower() for word in ('error', 'failed', 'exception', 'traceback', 'fatal')):
            return 'stderr'
        return f"svc_{record['service']}"

    def _insert_log(self, record: dict[str, str]) -> None:
        selected = self.filter_var.get()
        if selected != '全部' and selected != record['service']:
            return
        self.log_text.configure(state='normal')
        start = self.log_text.index('end-1c')
        self.log_text.insert('end', f"[{record['ts']}] [{record['service']}] {record['text']}\n")
        self.log_text.tag_add(self._tag_for(record), start, self.log_text.index('end-1c'))
        self.log_text.configure(state='disabled')
        if self.autoscroll_var.get():
            self.log_text.see('end')

    def render_empty(self) -> None:
        self.log_text.configure(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.configure(state='disabled')

    def render_history(self) -> None:
        self.render_empty()
        for record in self.manager.log_buffer:
            self._insert_log(record)

    def _refresh(self) -> None:
        self.manager.refresh_service_states(refresh_health=True)

    def _stop_all(self) -> None:
        if messagebox.askyesno('停止项目', '只会停止本工具登记为已管理的服务。是否继续？'):
            self.manager.stop_all()

    def _inspect(self, key: str) -> None:
        status, pid, detail = self.manager.status_for(key, refresh_health=True)
        if status != 'external':
            messagebox.showinfo('服务状态', f'{key}: {status}\n{detail or "没有外部端口占用。"}')
            return
        service = self.manager.services[key]
        if service.config.get('mode') == 'compose':
            question = 'Postgres 和 Redis 未由本工具启动。是否显式停止这两个容器？'
        else:
            question = f'{detail}\n\n该进程不是本工具启动的。是否停止其进程树？'
        if messagebox.askyesno('外部服务占用', question):
            self.manager.stop_service(key, force_external=True)

    def _refresh_cards(self) -> None:
        mapping = {
            'stopped': ('● 已停止', GRAY, '#1c2536'),
            'starting': ('● 启动中', YELLOW, '#2a210a'),
            'running': ('● 运行中', GREEN, '#0c2a1c'),
            'unhealthy': ('● 健康检查失败', RED, '#2a0f12'),
            'stopping': ('● 停止中', YELLOW, '#2a210a'),
            'external': ('● 外部进程占用', YELLOW, '#2a210a'),
            'unavailable': ('● 运行环境不可用', RED, '#2a0f12'),
            'error': ('● 异常', RED, '#2a0f12'),
        }
        for key, service in self.manager.services.items():
            label, foreground, background = mapping.get(service.status, mapping['stopped'])
            widgets = self.cards[key]
            widgets['status'].configure(text=label, fg=foreground, bg=background)
            started = service.started_at
            uptime = f'{int(time.time() - started)}s' if started and service.status in ('running', 'unhealthy') else '-'
            shown_pid = service.pid or '-'
            widgets['meta'].configure(text=f'PID: {shown_pid}   运行时长: {uptime}')
            busy = service.status in ('starting', 'stopping')
            widgets['start'].configure(state='disabled' if busy or service.status in ('running', 'unhealthy') else 'normal')
            widgets['stop'].configure(state='disabled' if busy or service.status in ('stopped', 'external') else 'normal')

    def _poll(self) -> None:
        self.manager.poll_log_files()
        try:
            while True:
                self._insert_log(self.manager.log_queue.get_nowait())
        except queue.Empty:
            pass
        if time.monotonic() - self._last_health_refresh >= 3 and not self._refresh_in_progress:
            self._refresh_in_progress = True

            def refresh() -> None:
                try:
                    self.manager.refresh_service_states(refresh_health=True)
                finally:
                    self._refresh_in_progress = False

            threading.Thread(target=refresh, daemon=True).start()
            self._last_health_refresh = time.monotonic()
        self._refresh_cards()
        self.root.after(300, self._poll)

    def _on_close(self) -> None:
        if any(self.manager._record(key) for key in self.manager.services):
            if messagebox.askyesno('退出管理器', '停止本工具启动的服务后退出？选择“否”会保留服务继续运行。'):
                self.root.withdraw()
                worker = threading.Thread(target=self.manager.stop_all, kwargs={'wait': True}, daemon=True)
                worker.start()

                def finish_when_stopped() -> None:
                    if worker.is_alive():
                        self.root.after(200, finish_when_stopped)
                    else:
                        self.root.destroy()

                finish_when_stopped()
                return
        self.root.destroy()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='机器人集群调度系统服务管理器')
    parser.add_argument('--config', type=Path, help='使用指定的 JSON 配置文件')
    subparsers = parser.add_subparsers(dest='command')
    subparsers.add_parser('gui', help='打开桌面管理界面')
    subparsers.add_parser('status', help='显示服务、端口和健康状态')
    start = subparsers.add_parser('start', help='启动一个服务或整个项目')
    start.add_argument('service', choices=['all', *DEFAULT_CONFIG['services'].keys()])
    stop = subparsers.add_parser('stop', help='停止本工具启动的服务')
    stop.add_argument('service', choices=['all', *DEFAULT_CONFIG['services'].keys()])
    stop.add_argument('--force-external', action='store_true', help='显式停止占用端口的非受管进程')
    logs = subparsers.add_parser('logs', help='输出持久化服务日志')
    logs.add_argument('service', choices=list(DEFAULT_CONFIG['services'].keys()))
    logs.add_argument('--tail', type=int, default=200, help='输出最后 N 行 (默认 200)')
    logs.add_argument('--follow', action='store_true', help='持续跟随日志')
    subparsers.add_parser('doctor', help='检查本机依赖、配置和端口')
    subparsers.add_parser('init-env', help='将本地占位密钥替换为随机值（不输出密钥）')
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        config = load_config(args.config)
    except (OSError, json.JSONDecodeError) as exc:
        print(f'Configuration load failed: {exc}', file=sys.stderr)
        return 1
    manager = ProcessManager(config)
    command = args.command or 'gui'
    if command == 'gui':
        root = tk.Tk()
        ManagerApp(root, manager)
        root.mainloop()
        return 0
    if command == 'status':
        print(format_status(manager.status_rows(refresh_health=True)))
        return 0
    if command == 'start':
        if args.service == 'all':
            manager.start_all(wait=True)
        else:
            manager.start_service(args.service, wait=True)
        rows = manager.status_rows(refresh_health=True)
        print(format_status(rows))
        requested = set(manager.services) if args.service == 'all' else {args.service}
        return 0 if all(status == 'running' for key, status, _pid, _detail in rows if key in requested) else 1
    if command == 'stop':
        if args.service == 'all':
            manager.stop_all(wait=True)
        else:
            manager.stop_service(args.service, force_external=args.force_external, wait=True)
        rows = manager.status_rows(refresh_health=False)
        print(format_status(rows))
        requested = set(manager.services) if args.service == 'all' else {args.service}
        return 0 if all(status == 'stopped' for key, status, _pid, _detail in rows if key in requested) else 1
    if command == 'logs':
        return cli_logs(manager, args.service, max(0, args.tail), args.follow)
    if command == 'doctor':
        healthy, lines = manager.doctor()
        print('\n'.join(lines))
        return 0 if healthy else 1
    if command == 'init-env':
        changed = initialize_local_env(ROOT / 'backend' / '.env')
        print('Generated local secrets in backend/.env.' if changed else 'Local secrets are already configured; no changes were made.')
        return 0
    parser.print_help()
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
