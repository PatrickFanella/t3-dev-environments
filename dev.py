#!/usr/bin/env python3
"""Worktree-scoped dev/test environments. Source checkouts and live data are not mounted."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import socket
import subprocess
import sys
import time
import urllib.request

HERE = Path(__file__).resolve().parent
STATE = Path.home() / '.local/state/t3-dev-environments/fleet'
IMAGE = 't3-dev-tools:20260924-v3'
PROFILES = json.loads((HERE / 'profiles.json').read_text())
BLOCKED_NAMES = {'client_secret.json', 'credentials.json', 'token.json', 'tokens.json'}
EXCLUDED_PARTS = {'.git', 'node_modules', '.venv', '.next', '__pycache__', '.t3', '.claude', '.blacktower', '.playwright-cli'}


def run(argv, *, cwd=None, capture=False, check=True, **kwargs):
    return subprocess.run(argv, cwd=cwd, check=check, text=True,
                          stdout=subprocess.PIPE if capture else None, **kwargs)


def report_address_pool_exhaustion():
    """List stopped Compose owners without removing any of their resources."""
    print('Docker address pools are exhausted. Stop a finished environment to release its network; '
          'do not prune other threads or remove data volumes.', file=sys.stderr)
    try:
        networks = run(['docker', 'network', 'ls', '--format', '{{json .}}'], capture=True)
        containers = run(['docker', 'ps', '-a', '--format', '{{json .}}'], capture=True)
        owners = {}
        for line in containers.stdout.splitlines():
            container = json.loads(line)
            labels = dict(label.split('=', 1) for label in container.get('Labels', '').split(',') if '=' in label)
            project = labels.get('com.docker.compose.project')
            if project:
                owners.setdefault(project, []).append(container['State'])
        groups = {}
        for line in networks.stdout.splitlines():
            network = json.loads(line)
            # Network ls does not expose labels; inspect only Compose networks.
            if network.get('Driver') != 'bridge':
                continue
            inspected = run(['docker', 'network', 'inspect', network['ID']], capture=True)
            project = (json.loads(inspected.stdout)[0].get('Labels') or {}).get('com.docker.compose.project')
            if project and all(state in {'exited', 'created', 'dead'} for state in owners.get(project, [])):
                groups.setdefault(project, []).append(network['Name'])
        for project, names in sorted(groups.items()):
            print(f'  Review owner {project}: {len(owners.get(project, []))} stopped containers; '
                  f'networks: {", ".join(sorted(names))}', file=sys.stderr)
        if not groups:
            print('  No stopped Compose projects found. Review host address-pool capacity.', file=sys.stderr)
        print('Use the owning worktree’s Stop Dev action, or its original Compose file with '
              'docker compose down (without --volumes). No resources were removed.', file=sys.stderr)
    except (subprocess.CalledProcessError, ValueError, KeyError, OSError) as error:
        print(f'Could not list network owners: {error}. Original command failure is preserved.', file=sys.stderr)


def compose_run(argv, *, capture=False, check=True):
    if capture:
        result = run(argv, capture=True, check=False, stderr=subprocess.PIPE)
        if result.stderr:
            print(result.stderr, end='', file=sys.stderr)
    else:
        # Compose progress is on stderr. Stream it while retaining a bounded error tail.
        tail = ''
        with subprocess.Popen(argv, text=True, stderr=subprocess.PIPE) as process:
            for line in process.stderr:
                print(line, end='', file=sys.stderr, flush=True)
                tail = (tail + line)[-65536:]
            result = subprocess.CompletedProcess(argv, process.wait(), stderr=tail)
    if result.returncode and 'all predefined address pools have been fully subnetted' in result.stderr:
        report_address_pool_exhaustion()
    if check:
        result.check_returncode()
    return result


def safe_file(name, tracked=False):
    p = Path(name)
    return (not p.is_absolute() and '..' not in p.parts
            and not EXCLUDED_PARTS.intersection(p.parts)
            and not any(x.startswith('.env') and x not in {'.env.example', '.env.sample', '.env.template'} for x in p.parts)
            and p.name not in BLOCKED_NAMES
            and p.suffix.lower() not in {'.pem', '.key', '.p12', '.pfx', '.sqlite', '.db'}
            and (tracked or p.suffix.lower() not in {'.xlsx', '.xls'}))


def source_root():
    result = run(['git', 'rev-parse', '--show-toplevel'], capture=True, check=False,
                 stderr=subprocess.DEVNULL)
    if result.returncode:
        raise ValueError('Run this action inside a Git project, not the home-directory project.')
    return Path(result.stdout.strip()).resolve()


def identify(root):
    if root.name in PROFILES:
        return root.name
    remote = run(['git', '-C', str(root), 'remote', 'get-url', 'origin'], capture=True, check=False).stdout.strip()
    name = remote.rsplit('/', 1)[-1].removesuffix('.git')
    if name in PROFILES:
        return name
    for name, profile in PROFILES.items():
        if any((root / marker).exists() for marker in profile.get('identity', [])):
            return name
    raise ValueError('No reviewed recipe for this repository. Available: ' + ', '.join(PROFILES))


@contextlib.contextmanager
def lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


class Environment:
    def __init__(self, root, profile, test=False):
        self.root = root.resolve()
        self.name = profile
        self.recipe = PROFILES[profile]
        self.key = hashlib.sha256(str(self.root).encode()).hexdigest()[:12]
        self.project = f't3dev-{profile}-{self.key}' + ('-test' if test else '')
        self.directory = STATE / self.project
        self.directory.mkdir(parents=True, exist_ok=True)
        self.source = self.directory / 'source'
        self.source.mkdir(exist_ok=True)
        self.file = self.directory / 'compose.json'
        self.testing = test

    def snapshot(self):
        tracked = set(run(['git', '-C', str(self.root), 'ls-files', '-z', '--cached'], capture=True).stdout.split('\0'))
        others = run(['git', '-C', str(self.root), 'ls-files', '-z', '--others', '--exclude-standard'], capture=True).stdout.split('\0')
        names = tracked | set(others)
        copied = {}
        for name in sorted(set(names)):
            if not name or not safe_file(name, name in tracked):
                continue
            source = self.root / name
            if not source.exists() or source.is_dir():
                continue
            if not source.resolve().is_relative_to(self.root):
                continue
            # Materialize internal links so the sandbox cannot reach the host.
            destination = self.source / name
            for parent in reversed(destination.parents):
                if parent == self.source or parent.is_relative_to(self.source):
                    if parent.is_symlink():
                        raise ValueError(f'Snapshot parent became a symlink: {parent}')
            if destination.is_symlink():
                destination.unlink()
            destination.parent.mkdir(parents=True, exist_ok=True)
            stat = source.stat()
            copied[name] = [stat.st_size, stat.st_mtime_ns]
            if not destination.exists() or (destination.stat().st_mtime_ns, destination.stat().st_size) != (stat.st_mtime_ns, stat.st_size):
                shutil.copy2(source, destination)
        manifest = self.directory / 'source-files.json'
        previous = json.loads(manifest.read_text()) if manifest.exists() else {}
        for name in previous.keys() - copied.keys():
            destination = self.source / name
            if not destination.parent.resolve().is_relative_to(self.source):
                raise ValueError('Snapshot deletion escaped the source directory.')
            destination.unlink(missing_ok=True)
        manifest.write_text(json.dumps(copied, sort_keys=True))
        revision = run(['git', '-C', str(self.root), 'rev-parse', 'HEAD'], capture=True).stdout.strip()
        (self.directory / 'identity.json').write_text(json.dumps({'source': str(self.root), 'profile': self.name, 'revision': revision, 'snapshotAt': time.time()}, indent=2))
        # Some repository checks use git ls-files. Maintain a source-only index.
        if not (self.source / '.git').exists():
            run(['git', 'init', '-q', str(self.source)])
        if copied and copied != previous:
            run(['git', '-C', str(self.source), 'add', '-u'], capture=True)
            run(['git', '-C', str(self.source), 'add', '-f', '--pathspec-from-file=-', '--pathspec-file-nul'],
                input='\0'.join(copied) + '\0', capture=True)
        return copied != previous

    def compose(self):
        port_file = self.directory / 'port'
        if not port_file.exists():
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                port_file.write_text(str(listener.getsockname()[1]))
        preview_port = int(port_file.read_text())
        cache = self.directory / 'cache'
        cache.mkdir(exist_ok=True)
        data = self.directory / 'data'
        data.mkdir(exist_ok=True)
        environment = {
            'HOME': '/cache', 'GOMAXPROCS': '2', 'GOCACHE': '/cache/go-build', 'GOMODCACHE': '/cache/go-mod',
            'GOFLAGS': '-buildvcs=false', 'CI': 'true', 'NEXT_TELEMETRY_DISABLED': '1',
            'DATABASE_URL': 'postgres://dev:disposable-dev-only@db:5432/dev?sslmode=disable',
            'REDIS_URL': 'redis://redis:6379/0', 'NODE_ENV': 'development',
            **self.recipe.get('env', {}),
        }
        for key in self.recipe.get('origin_env', []):
            environment[key] = f'http://127.0.0.1:{preview_port}'
        services = {}
        db = self.recipe.get('test_db', self.recipe.get('db')) if self.testing else self.recipe.get('db')
        if db:
            database = self.recipe.get('database', 'dev')
            database_user = self.recipe.get('database_user', 'dev')
            services['db'] = {
                'image': db, 'environment': {'POSTGRES_USER': database_user, 'POSTGRES_PASSWORD': 'disposable-dev-only', 'POSTGRES_DB': database},
                'healthcheck': {'test': ['CMD-SHELL', f'pg_isready -U {database_user} -d {database}'], 'interval': '2s', 'timeout': '3s', 'retries': 45},
                'mem_limit': '768m', 'cpus': 1,
                **({'tmpfs': ['/var/lib/postgresql/data']} if self.testing else {'volumes': ['database:/var/lib/postgresql/data']}),
            }
        if self.recipe.get('redis'):
            services['redis'] = {'image': 'redis:7-alpine', 'command': ['redis-server', '--save', '', '--appendonly', 'no'], 'mem_limit': '128m', 'cpus': 0.5}
        for name, service in self.recipe.get('services', {}).items():
            services[name] = service
        common = {
            'image': IMAGE, 'init': True, 'user': f'{os.getuid()}:{os.getgid()}',
            'working_dir': '/workspace', 'volumes': [f'{self.source}:/workspace:z', f'{cache}:/cache:z', f'{data}:/data:z'],
            'environment': environment, 'cpus': 2, 'mem_limit': '4g', 'pids_limit': 512,
            'security_opt': ['no-new-privileges:true'], 'cap_drop': ['ALL'],
        }
        services['tools'] = {**common, 'profiles': ['tools'], 'networks': ['dependencies'], 'command': ['true']}
        check_env = {key: value for key, value in environment.items() if key in {
            'HOME', 'GOMAXPROCS', 'GOCACHE', 'GOMODCACHE', 'GOFLAGS', 'CI', 'NEXT_TELEMETRY_DISABLED'}}
        services['checks'] = {**common, 'environment': {**check_env, **self.recipe.get('test_env', {})},
                              'profiles': ['tools'], 'command': ['true']}
        if self.recipe.get('start'):
            start = self.recipe['start']
            if ' & ' in start:
                backend, frontend = start.split(' & ', 1)
                start = f'bash -euc {shlex.quote(backend)} & bash -euc {shlex.quote(frontend)} & wait -n; exit 1'
            services['app'] = {**common, 'command': ['bash', '-euc', start]}
            proxy = self.directory / 'nginx.conf'
            proxy.write_text('events {}\nhttp { server { listen 8080; location / { '
                f'proxy_pass http://app:{self.recipe["port"]}; '
                'proxy_http_version 1.1; proxy_set_header Host $http_host; '
                'proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; '
                'proxy_read_timeout 300s; } } }\n')
            services['preview'] = {'image': 'nginx:1.28-alpine', 'networks': ['default', 'preview'],
                'ports': [f'127.0.0.1:{preview_port}:8080'], 'volumes': [f'{proxy}:/etc/nginx/nginx.conf:ro,z'],
                'depends_on': ['app'], 'mem_limit': '64m', 'cpus': 0.25,
                'security_opt': ['no-new-privileges:true']}
            if db:
                services['app']['depends_on'] = {'db': {'condition': 'service_healthy'}}
        config = {'services': services, 'networks': {
            'default': {'internal': True, 'driver_opts': {'com.docker.network.bridge.gateway_mode_ipv4': 'isolated'}},
            'dependencies': {}, 'preview': {}}, 'volumes': {'database': {}}}
        # Dependency installation can reach registries; running apps cannot reach external services.
        # Compose interpolates strings even in JSON exec-form command arrays.
        # These variables belong to the container shell, never the host shell.
        self.file.write_text(json.dumps(config, indent=2).replace('$', '$$'))

    def dc(self, *args, capture=False, check=True):
        return compose_run(['docker', 'compose', '--env-file', '/dev/null', '-p', self.project, '-f', str(self.file), *args], capture=capture, check=check)

    def setup(self):
        self.snapshot()
        self.compose()
        if run(['docker', 'image', 'inspect', IMAGE], capture=True, check=False, stderr=subprocess.DEVNULL).returncode:
            run(['docker', 'build', '-t', IMAGE, str(HERE)])
        try:
            self.dc('run', '--rm', '--no-deps', 'tools', 'bash', '-euc', self.recipe['setup'])
        finally:
            run(['docker', 'network', 'rm', self.project + '_dependencies'],
                capture=True, check=False, stderr=subprocess.DEVNULL)

    def url(self):
        binding = self.dc('port', 'preview', '8080', capture=True).stdout.strip()
        if not binding:
            raise ValueError('This environment is stopped. Run Start Dev first.')
        return 'http://' + binding

    def access_hint(self):
        host = socket.gethostname().lower()
        if host in {'dozor', 'almaz'}:
            return f'From Kvant: t3-preview {host} {self.name} open --root {shlex.quote(str(self.root))}'
        return ''

    def start(self):
        active = run(['docker', 'ps', '--filter', 'label=com.docker.compose.service=app',
                      '--format', '{{.Label "com.docker.compose.project"}}'], capture=True).stdout.splitlines()
        other = [p for p in active if p.startswith('t3dev-') and p != self.project]
        maximum = 2 if socket.gethostname().lower() == 'kvant' else 1
        if len(other) >= maximum:
            raise ValueError(f'Host limit ({maximum} dev stacks): stop an environment first: ' + ', '.join(other))
        self.setup()
        dependencies = [x for x in self.recipe.get('services', {})] + (['db'] if self.recipe.get('db') else []) + (['redis'] if self.recipe.get('redis') else [])
        if dependencies:
            self.dc('up', '-d', '--wait', '--wait-timeout', '180', *dependencies)
        self.dc('up', '-d', 'preview')
        url = self.url()
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            if not self.dc('ps', '--status', 'running', '-q', 'app', capture=True).stdout.strip():
                self.dc('logs', '--tail', '40', 'app')
                raise ValueError('Application exited before readiness; see the logs above.')
            try:
                with urllib.request.urlopen(url + self.recipe.get('health', '/'), timeout=3) as response:
                    if response.status == 200:
                        print(f'Preview: {url}\nSource: {self.root}\nEnvironment: {self.project}', flush=True)
                        if self.recipe.get('notes'):
                            print(self.recipe['notes'])
                        if self.access_hint():
                            print(self.access_hint())
                        return
            except Exception:
                time.sleep(2)
        self.dc('logs', '--tail', '40', 'app')
        raise ValueError('Preview did not become ready within 240 seconds.')

    def test(self, verify=False, command=None):
        self.setup()
        command = command or (self.recipe.get('verify') if verify else self.recipe.get('test'))
        if not command:
            raise ValueError('No test command exists for this profile.')
        # Only explicitly requested services start, in this test-only project.
        if self.recipe.get('test_services'):
            self.dc('up', '-d', '--wait', '--wait-timeout', '180', *self.recipe['test_services'])
        # Use the test stack network, without external credentials or runtime data.
        self.dc('run', '--rm', '--no-deps', 'checks', 'bash', '-euc', command)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', choices=sorted(PROFILES))
    parser.add_argument('action', choices=['setup', 'start', 'sync', 'watch', 'test', 'verify', 'url', 'logs', 'stop', 'status', 'list'])
    parser.add_argument('--command', help='Explicit shell command inside the isolated test environment (test/verify only)')
    args = parser.parse_args()
    if args.command is not None and (args.action not in {'test', 'verify'} or not args.command.strip()):
        parser.error('--command requires test or verify and a nonempty command')
    if args.action == 'list':
        for p in STATE.glob('*/identity.json'):
            print(p.parent.name, json.loads(p.read_text())['source'])
        return
    root = source_root()
    env = Environment(root, args.profile or identify(root), args.action in {'test', 'verify'})
    if args.action == 'watch':
        print('Watching source; Ctrl-C stops watching, not the app.', flush=True)
        while True:
            with lock(env.directory / 'lock'):
                if env.snapshot():
                    env.dc('restart', 'app')
            time.sleep(2)
    with lock(env.directory / 'lock'):
        if args.action == 'setup':
            env.setup()
        elif args.action == 'start':
            with lock(STATE / 'host-start.lock'):
                env.start()
        elif args.action == 'sync':
            env.snapshot()
            env.dc('restart', 'app')
            print(env.url())
        elif args.action in {'test', 'verify'}:
            with lock(STATE / 'host-test.lock'):
                try:
                    env.test(args.action == 'verify', args.command)
                finally:
                    if env.file.exists():
                        env.dc('--profile', 'tools', 'down', '--volumes', check=False)
        elif args.action == 'url':
            print(env.url())
            if env.access_hint():
                print(env.access_hint())
        elif args.action == 'stop':
            env.dc('--profile', 'tools', 'down')
        elif args.action == 'logs':
            env.dc('logs', '--tail', '100', '-f', 'app')
        elif args.action == 'status':
            env.dc('ps')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(error.returncode if isinstance(error, subprocess.CalledProcessError) else 1)
    except KeyboardInterrupt:
        sys.exit(130)
