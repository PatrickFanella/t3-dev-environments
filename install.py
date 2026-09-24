#!/usr/bin/env python3
"""Install T3 script overrides without restarting T3 or writing its database."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sqlite3

HERE = Path(__file__).resolve().parent
home = Path.home()
destination = home / '.local/share/t3-dev-environments'
destination.mkdir(parents=True, exist_ok=True)
for name in ['dev.py', 'remote.py', 'profiles.json', 'Dockerfile', 'install.py']:
    if HERE != destination:
        shutil.copy2(HERE / name, destination / name)
bin_dir = home / '.local/bin'
bin_dir.mkdir(parents=True, exist_ok=True)
for command, script in [('t3-dev', 'dev.py'), ('t3-preview', 'remote.py')]:
    target = destination / script
    target.chmod(0o755)
    link = bin_dir / command
    if link.is_symlink() and link.resolve() == target:
        continue
    if link.exists() or link.is_symlink():
        raise SystemExit(f'Preserving existing command: {link}')
    link.symlink_to(target)

profiles = json.loads((HERE / 'profiles.json').read_text())
settings = home / '.t3/userdata/settings.json'
before = settings.read_bytes()
config = json.loads(before)
db = sqlite3.connect(f'file:{home}/.t3/userdata/state.sqlite?mode=ro', uri=True)
projects = db.execute('SELECT project_id,title,workspace_root,scripts_json FROM projection_projects WHERE deleted_at IS NULL').fetchall()
db.close()
overrides = config.setdefault('projectSettingsOverrides', {})
installed = []
for ident, title, root, base_scripts in projects:
    name = Path(root).name
    if name not in profiles:
        continue
    # Preserve the already-qualified repository-owned Subcult OS setup on Kvant.
    if name == 'subcult-os' and socket.gethostname().lower() == 'kvant':
        continue
    if not (Path(root) / '.git').exists():
        continue
    scripts = []
    for action, label in [('setup', 'Setup Worktree'), ('start', 'Start Dev'),
                          ('watch', 'Watch Changes'), ('sync', 'Sync Changes'),
                          ('url', 'Preview URL'), ('test', 'Test'),
                          ('verify', 'Check Code'), ('status', 'Dev Status'),
                          ('logs', 'Dev Logs'), ('stop', 'Stop Dev')]:
        scripts.append({'id': 'fleet-' + hashlib.sha256((ident + action).encode()).hexdigest()[:12],
                        'name': label, 'icon': 'play', 'runOnWorktreeCreate': action == 'setup',
                        'async': False if action == 'setup' else True,
                        'command': f'python3 "$HOME/.local/share/t3-dev-environments/dev.py" --profile {name} {action}'})
    current = overrides.setdefault(ident, {})
    # Preserve manually configured actions; replace only this launcher's own actions.
    existing = [s for s in current.get('defaultProjectScripts', json.loads(base_scripts)) if not s.get('id', '').startswith('fleet-')]
    current.update(defaultProjectScripts=existing + scripts, defaultThreadEnvMode='worktree')
    installed.append({'id': ident, 'project': title, 'root': root, 'actions': len(scripts)})

stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
backup = home / '.local/state/t3-dev-environments' / ('install-' + stamp)
backup.mkdir(parents=True, exist_ok=False)
(backup / 'settings.before.json').write_bytes(before)
(backup / 'installed.json').write_text(json.dumps(installed, indent=2) + '\n')
if settings.read_bytes() != before:
    raise SystemExit('T3 settings changed concurrently; preserved them. Rerun installation.')
temporary = settings.with_name('settings.fleet-tmp.json')
temporary.write_text(json.dumps(config, indent=2) + '\n')
temporary.chmod(settings.stat().st_mode & 0o777)
temporary.replace(settings)
print(json.dumps({'host': socket.gethostname(), 'projects': installed, 'backup': str(backup)}, indent=2))
