#!/usr/bin/env python3
"""Reliable Docker Compose deployment controller for RobotsSystem."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
COMPOSE_FILE = ROOT / 'compose.deploy.yml'
DEFAULT_ENV_FILE = ROOT / 'deploy' / '.env'
VERSION_FILE = ROOT / 'VERSION'
PROJECT_NAME = 'robots-system-deploy'
SERVICES = ('postgres', 'redis', 'backend', 'pm', 'om')
LOCAL_IMAGES = {
    'backend': f'{PROJECT_NAME}-backend:latest',
    'pm': f'{PROJECT_NAME}-pm:latest',
    'om': f'{PROJECT_NAME}-om:latest',
    'postgres': 'postgres:16-alpine',
    'redis': 'redis:7.2-alpine',
}
OFFLINE_IMAGES = tuple(LOCAL_IMAGES.values())
RELEASE_INPUTS = (
    Path('VERSION'),
    Path('CHANGELOG.md'),
    Path('compose.deploy.yml'),
    Path('README.md'),
    Path('backend'),
    Path('frontend'),
    Path('manager/deploy.py'),
    Path('manager/deploy.bat'),
    Path('deploy/.env.example'),
    Path('deploy/install.ps1'),
    Path('deploy/install.cmd'),
    Path('deploy/manage.ps1'),
    Path('deploy/manage.cmd'),
    Path('docs/部署与运维手册.md'),
    Path('docs/使用手册.md'),
    Path('docs/设备开发与接入规范.md'),
    Path('docs/DEVICE_GATEWAY_API.md'),
    Path('docs/版本发布与升级.md'),
)
RELEASE_EXCLUDED_DIRS = {
    '.git', '.pytest_cache', '.ruff_cache', '.venv', '__pycache__',
    'backups', 'dist', 'node_modules', 'runtime', 'tests',
}
SECRET_NAMES = (
    'PG_PASSWORD',
    'REDIS_PASSWORD',
    'JWT_SECRET',
    'DEVICE_GATEWAY_API_KEY',
    'INITIAL_SETUP_TOKEN',
)
SEMVER_PATTERN = re.compile(
    r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)'
    r'(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$'
)
REGISTRY_PREFIX_PATTERN = re.compile(
    r'^[a-z0-9]+(?:[.-][a-z0-9]+)*(?::[0-9]+)?'
    r'(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)+$'
)


def project_version() -> str:
    """Return the repository SemVer value."""
    return normalize_version(VERSION_FILE.read_text(encoding='utf-8').strip())


def normalize_version(value: str) -> str:
    """Normalize an optional v-prefixed SemVer value."""
    normalized = value.strip()
    if normalized.startswith('v'):
        normalized = normalized[1:]
    if not SEMVER_PATTERN.fullmatch(normalized):
        raise ValueError(f'Invalid semantic version: {value}')
    return normalized


def registry_images(prefix: str, version: str) -> dict[str, str]:
    """Build immutable application image references for one release."""
    normalized_prefix = prefix.strip().rstrip('/')
    if not REGISTRY_PREFIX_PATTERN.fullmatch(normalized_prefix):
        raise ValueError('Registry prefix must be a lowercase image path without a URL scheme.')
    tag = f'v{normalize_version(version)}'
    return {
        'backend': f'{normalized_prefix}-backend:{tag}',
        'pm': f'{normalized_prefix}-pm:{tag}',
        'om': f'{normalized_prefix}-om:{tag}',
        'postgres': LOCAL_IMAGES['postgres'],
        'redis': LOCAL_IMAGES['redis'],
    }


def parse_env(path: Path) -> dict[str, str]:
    """Read a simple dotenv file without evaluating shell syntax."""
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        name, value = line.split('=', 1)
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def is_placeholder(value: str) -> bool:
    """Identify committed examples and commonly reused weak values."""
    normalized = value.strip().lower()
    return (
        not normalized
        or normalized.startswith('replace-with-')
        or normalized in {'changeme', 'change-me', 'password', 'secret', 'scheduler123'}
        or normalized.startswith('<')
    )


def generate_env() -> str:
    """Create a complete production dotenv payload without printing secrets."""
    values = {
        'APP_NAME': 'RobotsClusterScheduler',
        'RELEASE_VERSION': project_version(),
        'BIND_HOST': '0.0.0.0',
        'BACKEND_PORT': '8000',
        'PM_PORT': '8080',
        'OM_PORT': '8081',
        'PG_USER': 'scheduler',
        'PG_PASSWORD': secrets.token_urlsafe(32),
        'PG_DB': 'scheduler',
        'REDIS_PASSWORD': secrets.token_urlsafe(32),
        'JWT_SECRET': secrets.token_urlsafe(48),
        'DEVICE_GATEWAY_API_KEY': secrets.token_urlsafe(48),
        'INITIAL_SETUP_TOKEN': secrets.token_urlsafe(32),
    }
    groups = (
        ('APP_NAME', 'RELEASE_VERSION', 'BIND_HOST', 'BACKEND_PORT', 'PM_PORT', 'OM_PORT'),
        ('PG_USER', 'PG_PASSWORD', 'PG_DB', 'REDIS_PASSWORD'),
        ('JWT_SECRET', 'DEVICE_GATEWAY_API_KEY', 'INITIAL_SETUP_TOKEN'),
    )
    return '\n\n'.join('\n'.join(f'{name}={values[name]}' for name in group) for group in groups) + '\n'


def compose_base(env_file: Path) -> list[str]:
    return [
        'docker', 'compose',
        '--project-name', PROJECT_NAME,
        '--file', str(COMPOSE_FILE),
        '--env-file', str(env_file),
    ]


def run(command: list[str], timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    """Run a visible command and return its exact exit status."""
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=timeout,
        check=False,
    )


def capture(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        timeout=timeout,
        check=False,
    )


def compose_snapshot(env_file: Path) -> dict[str, dict[str, Any]]:
    """Return normalized service state from Docker Compose JSON output."""
    completed = capture(compose_base(env_file) + ['ps', '--all', '--format', 'json'])
    if completed.returncode != 0:
        return {}
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


def deployment_healthy(env_file: Path) -> bool:
    snapshot = compose_snapshot(env_file)
    for service in SERVICES:
        item = snapshot.get(service)
        if not item or str(item.get('State', '')).lower() != 'running':
            return False
        health = str(item.get('Health', '')).lower()
        if health and health != 'healthy':
            return False
    return True


def wait_until_healthy(env_file: Path, timeout: int = 240) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if deployment_healthy(env_file):
            return True
        time.sleep(2)
    return False


def http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=4) as response:
            return 200 <= response.status < 400
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


def validate_env(env_file: Path) -> list[str]:
    errors: list[str] = []
    if not env_file.is_file():
        return [f'Deployment environment file does not exist: {env_file}']
    values = parse_env(env_file)
    required = {
        'APP_NAME', 'BIND_HOST', 'BACKEND_PORT', 'PM_PORT', 'OM_PORT',
        'PG_USER', 'PG_PASSWORD', 'PG_DB', 'REDIS_PASSWORD',
        'JWT_SECRET', 'DEVICE_GATEWAY_API_KEY', 'INITIAL_SETUP_TOKEN',
    }
    for name in sorted(required):
        if not values.get(name):
            errors.append(f'{name} is missing.')
    for name in SECRET_NAMES:
        value = values.get(name, '')
        if is_placeholder(value):
            errors.append(f'{name} is still a placeholder or weak default.')
        elif len(value) < 24:
            errors.append(f'{name} must contain at least 24 characters.')
    secrets_in_use = [values.get(name, '') for name in SECRET_NAMES]
    if len(set(secrets_in_use)) != len(secrets_in_use):
        errors.append('Deployment secrets must all be different.')
    for name in ('BACKEND_PORT', 'PM_PORT', 'OM_PORT'):
        value = values.get(name, '')
        if not value.isdigit() or not 1 <= int(value) <= 65535:
            errors.append(f'{name} must be a valid TCP port.')
    return errors


def doctor(env_file: Path) -> bool:
    """Validate Docker, Compose, configuration, and the rendered model."""
    errors = validate_env(env_file)
    checks = (
        (['docker', 'info', '--format', '{{.ServerVersion}}'], 'Docker engine'),
        (['docker', 'compose', 'version'], 'Docker Compose'),
    )
    for command, label in checks:
        try:
            completed = capture(command, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            completed = None
        if completed is None or completed.returncode != 0:
            errors.append(f'{label} is unavailable.')
        else:
            print(f'OK   {label}')
    required_images = ('python:3.12-slim', 'node:22-alpine', 'nginx:1.27-alpine', 'postgres:16-alpine', 'redis:7.2-alpine')
    missing_images: list[str] = []
    for image in required_images:
        cached = capture(['docker', 'image', 'inspect', image], timeout=10)
        if cached.returncode != 0:
            missing_images.append(image)
    if missing_images:
        try:
            registry = capture(['docker', 'manifest', 'inspect', missing_images[0]], timeout=30)
        except subprocess.TimeoutExpired:
            registry = None
        if registry is None or registry.returncode != 0:
            errors.append(
                'Required images are not cached and Docker Hub is unreachable: '
                + ', '.join(missing_images)
            )
        else:
            print('OK   Docker registry is reachable for missing base images.')
    else:
        print('OK   Required base images are cached locally.')
    if not errors:
        rendered = capture(compose_base(env_file) + ['config', '--quiet'], timeout=30)
        if rendered.returncode != 0:
            errors.append('Compose configuration is invalid. Run the command again to inspect Docker output.')
        else:
            print('OK   Compose configuration')
    if errors:
        for error in errors:
            print(f'FAIL {error}', file=sys.stderr)
        return False
    print('OK   Deployment secrets are present, non-placeholder, and distinct.')
    return True


def init_env(env_file: Path) -> int:
    if env_file.exists():
        print(f'Refusing to overwrite existing deployment secrets: {env_file}', file=sys.stderr)
        return 1
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(generate_env(), encoding='utf-8')
    if os.name != 'nt':
        env_file.chmod(0o600)
    print(f'Created deployment configuration: {env_file}')
    print('Secrets were generated locally and were not printed.')
    return 0


def release_files() -> list[tuple[Path, Path]]:
    """Return the deployment-only source set and its archive paths."""
    files: list[tuple[Path, Path]] = []
    remapped = {
        Path('deploy/install.ps1'): Path('install.ps1'),
        Path('deploy/install.cmd'): Path('install.cmd'),
        Path('deploy/manage.ps1'): Path('manage.ps1'),
        Path('deploy/manage.cmd'): Path('manage.cmd'),
    }
    for relative_input in RELEASE_INPUTS:
        source = ROOT / relative_input
        if source.is_file():
            candidates = [source]
        else:
            candidates = []
            for current, directories, names in os.walk(source):
                directories[:] = sorted(
                    name for name in directories if name not in RELEASE_EXCLUDED_DIRS
                )
                candidates.extend(Path(current) / name for name in sorted(names))
        for candidate in candidates:
            if not candidate.is_file():
                continue
            relative = candidate.relative_to(ROOT)
            if any(part in RELEASE_EXCLUDED_DIRS for part in relative.parts):
                continue
            if candidate.name == '.env' or candidate.suffix.lower() in {'.log', '.pyc'}:
                continue
            archive_path = remapped.get(relative, relative)
            files.append((candidate, archive_path))
    return sorted(files, key=lambda item: item[1].as_posix())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def create_offline_image_archive(target: Path, env_file: Path, version: str) -> bool:
    """Build current application images and export every runtime image."""
    generated_env = tempfile.TemporaryDirectory(prefix='robots-release-env-')
    package_env = Path(generated_env.name) / '.env'
    base_content = env_file.read_text(encoding='utf-8') if env_file.is_file() else generate_env()
    lines = [line for line in base_content.splitlines() if not line.startswith('RELEASE_VERSION=')]
    package_env.write_text(
        '\n'.join(lines + [f'RELEASE_VERSION={normalize_version(version)}', '']),
        encoding='utf-8',
    )
    try:
        for image in ('postgres:16-alpine', 'redis:7.2-alpine'):
            if capture(['docker', 'image', 'inspect', image], timeout=20).returncode != 0:
                if run(['docker', 'pull', image]).returncode != 0:
                    print(f'Unable to pull required runtime image: {image}', file=sys.stderr)
                    return False
        build = run(compose_base(package_env) + ['build', 'backend', 'pm', 'om'])
        if build.returncode != 0:
            return False
        for image in OFFLINE_IMAGES:
            if capture(['docker', 'image', 'inspect', image], timeout=20).returncode != 0:
                print(f'Offline image is missing after build: {image}', file=sys.stderr)
                return False
        print('Exporting offline runtime images. This can take several minutes...')
        return run(['docker', 'save', '--output', str(target), *OFFLINE_IMAGES]).returncode == 0
    finally:
        generated_env.cleanup()


def package_release(
    output_dir: Path,
    offline: bool,
    env_file: Path,
    version: str | None = None,
    registry_prefix: str | None = None,
    overwrite: bool = False,
) -> int:
    """Create a portable deployment ZIP without local secrets or data."""
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        release_version = normalize_version(version or project_version())
        images = registry_images(registry_prefix, release_version) if registry_prefix else LOCAL_IMAGES
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    mode = 'offline' if offline else ('registry' if registry_prefix else 'source')
    archive = output_dir / f'RobotsSystem-v{release_version}-{mode}.zip'
    checksum = archive.with_suffix(archive.suffix + '.sha256')
    if not overwrite and (archive.exists() or checksum.exists()):
        print(f'Release already exists; increment VERSION or use --overwrite: {archive}', file=sys.stderr)
        return 1
    files = release_files()
    if not files:
        print('No release files were found.', file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix='robots-release-') as temporary:
        image_archive = Path(temporary) / 'images.tar'
        if offline and not create_offline_image_archive(image_archive, env_file, release_version):
            print('Offline image export failed; release package was not created.', file=sys.stderr)
            return 1

        manifest_files = {path.as_posix(): sha256_file(source) for source, path in files}
        if offline:
            manifest_files['deploy/images.tar'] = sha256_file(image_archive)
        manifest = {
            'format': 2,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'mode': mode,
            'version': release_version,
            'images': images,
            'files': manifest_files,
        }
        root_name = 'RobotsSystem'
        try:
            with zipfile.ZipFile(archive, 'w', allowZip64=True) as bundle:
                for source, relative in files:
                    bundle.write(
                        source,
                        f'{root_name}/{relative.as_posix()}',
                        compress_type=zipfile.ZIP_DEFLATED,
                    )
                if offline:
                    bundle.write(
                        image_archive,
                        f'{root_name}/deploy/images.tar',
                        compress_type=zipfile.ZIP_STORED,
                    )
                bundle.writestr(
                    f'{root_name}/release-manifest.json',
                    json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
                    compress_type=zipfile.ZIP_DEFLATED,
                )
        except Exception:
            archive.unlink(missing_ok=True)
            raise

    archive_hash = sha256_file(archive)
    checksum.write_text(f'{archive_hash}  {archive.name}\n', encoding='ascii')
    print(f'Release package created: {archive}')
    print(f'Checksum file created:  {checksum}')
    print('The package contains no deployment .env, credentials, logs, backups, or business data.')
    return 0


def deploy_up(env_file: Path) -> int:
    if not doctor(env_file):
        return 1
    snapshot = compose_snapshot(env_file)
    if str(snapshot.get('postgres', {}).get('State', '')).lower() == 'running':
        backup_path = create_backup(env_file)
        if backup_path is None:
            print('Pre-upgrade database backup failed; deployment was not changed.', file=sys.stderr)
            return 1
        print(f'Pre-upgrade backup created: {backup_path}')
    command = compose_base(env_file) + [
        'up', '--detach', '--build', '--remove-orphans',
        '--wait', '--wait-timeout', '240',
    ]
    completed = run(command)
    if completed.returncode != 0:
        return completed.returncode
    if not wait_until_healthy(env_file, timeout=30):
        print('Deployment containers did not reach a healthy state.', file=sys.stderr)
        return 1
    values = parse_env(env_file)
    probe_host = '127.0.0.1' if values['BIND_HOST'] == '0.0.0.0' else values['BIND_HOST']
    backend_url = f"http://{probe_host}:{values['BACKEND_PORT']}/ready"
    pm_url = f"http://{probe_host}:{values['PM_PORT']}/api/auth/setup-status"
    om_url = f"http://{probe_host}:{values['OM_PORT']}/api/auth/setup-status"
    if not all(http_ok(url) for url in (backend_url, pm_url, om_url)):
        print('Containers are healthy but published HTTP endpoints are unavailable.', file=sys.stderr)
        return 1
    print('Deployment is healthy.')
    print(f"Backend: http://127.0.0.1:{values['BACKEND_PORT']}")
    print(f"PM:      http://127.0.0.1:{values['PM_PORT']}")
    print(f"O&M:     http://127.0.0.1:{values['OM_PORT']}")
    return 0


def deploy_down(env_file: Path) -> int:
    if not env_file.is_file():
        print(f'Deployment environment file does not exist: {env_file}', file=sys.stderr)
        return 1
    completed = run(compose_base(env_file) + ['down', '--timeout', '60', '--remove-orphans'])
    if completed.returncode == 0:
        print('Deployment stopped. Database, Redis, and backup volumes were preserved.')
    return completed.returncode


def create_backup(env_file: Path) -> Path | None:
    """Export a custom-format PostgreSQL backup to the host filesystem."""
    if not env_file.is_file():
        print(f'Deployment environment file does not exist: {env_file}', file=sys.stderr)
        return None
    snapshot = compose_snapshot(env_file)
    if str(snapshot.get('postgres', {}).get('State', '')).lower() != 'running':
        print('PostgreSQL deployment container is not running.', file=sys.stderr)
        return None
    backup_dir = ROOT / 'deploy' / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target = backup_dir / f'robots_system_{timestamp}.dump'
    command = compose_base(env_file) + [
        'exec', '--no-TTY', 'postgres', 'sh', '-c',
        'PGPASSWORD="$POSTGRES_PASSWORD" exec pg_dump '
        '--format=custom --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"',
    ]
    with target.open('wb') as output:
        completed = subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0 or not target.exists() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        error = completed.stderr.decode('utf-8', errors='replace').strip()
        print(f'Database backup failed: {error}', file=sys.stderr)
        return None
    return target


def restore_backup(env_file: Path, backup_path: Path, confirmation: str) -> int:
    """Restore a host backup only after an explicit destructive confirmation."""
    if confirmation != 'RESTORE':
        print('Restore requires --confirm RESTORE.', file=sys.stderr)
        return 2
    backup_path = backup_path.resolve()
    if not backup_path.is_file():
        print(f'Backup file does not exist: {backup_path}', file=sys.stderr)
        return 1
    snapshot = compose_snapshot(env_file)
    if str(snapshot.get('postgres', {}).get('State', '')).lower() != 'running':
        print('PostgreSQL deployment container is not running.', file=sys.stderr)
        return 1
    stop_result = run(compose_base(env_file) + ['stop', '--timeout', '30', 'pm', 'om', 'backend'])
    if stop_result.returncode != 0:
        return stop_result.returncode
    command = compose_base(env_file) + [
        'exec', '--no-TTY', 'postgres', 'sh', '-c',
        'PGPASSWORD="$POSTGRES_PASSWORD" exec pg_restore --clean --if-exists '
        '--no-owner --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"',
    ]
    with backup_path.open('rb') as source:
        completed = subprocess.run(command, cwd=ROOT, stdin=source, check=False)
    if completed.returncode != 0:
        print('Restore failed. Application services remain stopped for inspection.', file=sys.stderr)
        return completed.returncode
    started = run(compose_base(env_file) + ['up', '--detach', '--wait', '--wait-timeout', '240', 'backend', 'pm', 'om'])
    if started.returncode != 0 or not wait_until_healthy(env_file, timeout=60):
        print('Restore completed, but application services did not become healthy.', file=sys.stderr)
        return 1
    print(f'Restored database from {backup_path}.')
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='RobotsSystem deployment controller')
    parser.add_argument('--env-file', type=Path, default=DEFAULT_ENV_FILE)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init', help='generate a new deployment .env with random secrets')
    commands.add_parser('doctor', help='validate Docker and deployment configuration')
    commands.add_parser('up', help='build and start the complete deployment')
    commands.add_parser('down', help='stop deployment while preserving all volumes')
    commands.add_parser('status', help='show deployment container status')
    commands.add_parser('backup', help='export a PostgreSQL backup to deploy/backups')
    restore = commands.add_parser('restore', help='restore a backup after explicit confirmation')
    restore.add_argument('backup', type=Path)
    restore.add_argument('--confirm', default='')
    restart = commands.add_parser('restart', help='restart one service or the full deployment')
    restart.add_argument('service', nargs='?', choices=SERVICES)
    logs = commands.add_parser('logs', help='show Docker service logs')
    logs.add_argument('service', nargs='?', choices=SERVICES)
    logs.add_argument('--follow', action='store_true')
    logs.add_argument('--tail', type=int, default=200)
    reset = commands.add_parser('reset-password', help='interactively reset an operator password')
    reset.add_argument('username')
    commands.add_parser('list-users', help='list operator accounts without password data')
    package = commands.add_parser('package', help='create a portable deployment ZIP')
    package.add_argument('--output', type=Path, default=ROOT / 'release')
    delivery = package.add_mutually_exclusive_group()
    delivery.add_argument(
        '--offline',
        action='store_true',
        help='include all runtime images so the target does not need a registry',
    )
    delivery.add_argument(
        '--registry-prefix',
        help='publish a package that pulls immutable images from this registry prefix',
    )
    package.add_argument('--version', help='SemVer release value; defaults to VERSION')
    package.add_argument('--overwrite', action='store_true')
    return parser


def main() -> int:
    args = build_parser().parse_args()
    env_file = args.env_file.resolve()
    if args.command == 'init':
        return init_env(env_file)
    if args.command == 'package':
        return package_release(
            args.output,
            args.offline,
            env_file,
            version=args.version,
            registry_prefix=args.registry_prefix,
            overwrite=args.overwrite,
        )
    if args.command == 'doctor':
        return 0 if doctor(env_file) else 1
    if args.command == 'up':
        return deploy_up(env_file)
    if args.command == 'down':
        return deploy_down(env_file)
    if not env_file.is_file():
        print(f'Deployment environment file does not exist: {env_file}', file=sys.stderr)
        return 1
    if args.command == 'status':
        result = run(compose_base(env_file) + ['ps', '--all'])
        return 0 if result.returncode == 0 and deployment_healthy(env_file) else 1
    if args.command == 'backup':
        backup_path = create_backup(env_file)
        if backup_path is None:
            return 1
        print(f'Backup created: {backup_path}')
        return 0
    if args.command == 'restore':
        return restore_backup(env_file, args.backup, args.confirm)
    if args.command == 'reset-password':
        return run(compose_base(env_file) + ['exec', 'backend', 'python', '-m', 'app.cli', 'reset-password', args.username]).returncode
    if args.command == 'list-users':
        return run(compose_base(env_file) + ['exec', '--no-TTY', 'backend', 'python', '-m', 'app.cli', 'list-users']).returncode
    if args.command == 'restart':
        command = compose_base(env_file) + ['restart']
        if args.service:
            command.append(args.service)
        result = run(command)
        if result.returncode != 0:
            return result.returncode
        return 0 if wait_until_healthy(env_file, timeout=180) else 1
    if args.command == 'logs':
        command = compose_base(env_file) + ['logs', '--tail', str(max(0, args.tail))]
        if args.follow:
            command.append('--follow')
        if args.service:
            command.append(args.service)
        return run(command).returncode
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
