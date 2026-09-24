#!/usr/bin/env python3
"""Open a remote development preview through an owned loopback SSH tunnel."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument('host', choices=['dozor', 'almaz'])
parser.add_argument('project')
parser.add_argument('action', choices=['start', 'open', 'stop', 'test', 'verify', 'status'], default='open', nargs='?')
parser.add_argument('--root', help='Remote T3 worktree path; defaults to the project checkout')
args = parser.parse_args()
profiles = json.loads((Path(__file__).resolve().parent / 'profiles.json').read_text())
if args.project not in profiles:
    parser.error('Unknown project')
root = args.root or '/home/onnwee/Work/T3/' + args.project
if not Path(root).is_absolute() or '..' in Path(root).parts:
    parser.error('--root must be an absolute checkout path')
runner = '/home/onnwee/.local/share/t3-dev-environments/dev.py'
command = ['python3', runner, '--profile', args.project]
state = Path.home() / '.local/state/t3-dev-environments/tunnels'
state.mkdir(parents=True, exist_ok=True)
import hashlib
control = str(state / (args.host + '-' + hashlib.sha256(root.encode()).hexdigest()[:12] + '.sock'))

def ssh(action, capture=False):
    return subprocess.run(['ssh', args.host, 'cd ' + shlex.quote(root) + ' && ' + shlex.join(command + [action])],
                          check=True, text=True, stdout=subprocess.PIPE if capture else None)

if args.action not in ['open', 'start']:
    ssh(args.action)
    if args.action == 'stop':
        subprocess.run(['ssh', '-S', control, '-O', 'exit', args.host], check=False)
    raise SystemExit(0)
if args.action == 'start':
    ssh('start')
url = ssh('url', capture=True).stdout.strip().splitlines()[0]
port = int(url.rsplit(':', 1)[-1])
check = subprocess.run(['ssh', '-S', control, '-O', 'check', args.host], capture_output=True)
if check.returncode:
    subprocess.run(['ssh', '-fNM', '-S', control, '-o', 'ExitOnForwardFailure=yes',
                    '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3',
                    '-L', f'127.0.0.1:{port}:127.0.0.1:{port}', args.host], check=True)
with urllib.request.urlopen(url, timeout=30) as response:
    if response.status != 200:
        raise SystemExit('Tunnel opened, but the preview did not return HTTP 200.')
print(f'{args.host} / {args.project}: {url}')
print('Tunnel stays open until Stop Dev through this command, SSH disconnect, or logout/reboot.')
