import json
import io
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import dev


class NetworkFailureTests(unittest.TestCase):
    def test_pool_error_reports_owners_and_preserves_exit_status(self):
        failure = subprocess.CompletedProcess(['docker', 'compose'], 17, '',
            'Error: all predefined address pools have been fully subnetted\n')
        with patch.object(dev, 'run', return_value=failure), patch.object(dev, 'report_address_pool_exhaustion') as report:
            with self.assertRaises(subprocess.CalledProcessError) as caught:
                dev.compose_run(['docker', 'compose'], capture=True)
            self.assertEqual(caught.exception.returncode, 17)
            report.assert_called_once()

    def test_other_failures_do_not_trigger_pool_advice(self):
        failure = subprocess.CompletedProcess(['docker', 'compose'], 3, '', 'Connection refused\n')
        with patch.object(dev, 'run', return_value=failure), patch.object(dev, 'report_address_pool_exhaustion') as report:
            self.assertEqual(dev.compose_run(['docker', 'compose'], capture=True, check=False).returncode, 3)
            report.assert_not_called()

    def test_diagnostic_excludes_live_projects_and_never_mutates_docker(self):
        networks = [{'ID': 'a', 'Name': 'finished_default', 'Driver': 'bridge'},
                    {'ID': 'b', 'Name': 'active_default', 'Driver': 'bridge'},
                    {'ID': 'c', 'Name': 'empty_default', 'Driver': 'bridge'}]
        containers = [{'State': 'exited', 'Labels': 'com.docker.compose.project=finished'},
                      {'State': 'running', 'Labels': 'com.docker.compose.project=active'}]
        replies = ['\n'.join(map(json.dumps, networks)), '\n'.join(map(json.dumps, containers))]
        replies += [json.dumps([{'Labels': {'com.docker.compose.project': p}}])
                    for p in ['finished', 'active', 'empty']]
        results = [subprocess.CompletedProcess([], 0, reply) for reply in replies]
        with patch.object(dev, 'run', side_effect=results) as run, patch('sys.stderr', new_callable=io.StringIO) as output:
            dev.report_address_pool_exhaustion()
            self.assertIn('Review owner finished', output.getvalue())
            self.assertIn('Review owner empty', output.getvalue())
            self.assertNotIn('Review owner active', output.getvalue())
            for call in run.call_args_list:
                self.assertIn(call.args[0][1:3], [['network', 'ls'], ['network', 'inspect'], ['ps', '-a']])

    def test_failed_diagnostic_stays_advisory(self):
        with patch.object(dev, 'run', side_effect=subprocess.CalledProcessError(1, ['docker'])), patch('sys.stderr', new_callable=io.StringIO) as output:
            dev.report_address_pool_exhaustion()
            self.assertIn('Original command failure is preserved', output.getvalue())


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / 'checkout'
        self.root.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        subprocess.run(['git', '-C', str(self.root), '-c', 'user.email=test@example.test',
                        '-c', 'user.name=Test', 'commit', '-qm', 'Initial', '--allow-empty'], check=True)
        self.state = patch.object(dev, 'STATE', self.base / 'state')
        self.state.start()
        self.env = dev.Environment(self.root, 'dash')

    def tearDown(self):
        self.state.stop()
        self.temp.cleanup()

    def test_snapshot_excludes_secrets_and_external_links_but_tracks_edits(self):
        for name in ['code.ts', '.env', '.env.local', 'client_secret.json', 'private.key',
                     'voters.xlsx', '.env.example']:
            (self.root / name).write_text(name)
        external = self.base / 'outside.txt'
        external.write_text('private')
        (self.root / 'escape.txt').symlink_to(external)
        (self.root / 'internal.ts').symlink_to(self.root / 'code.ts')
        self.assertTrue(self.env.snapshot())
        self.assertEqual(set(json.loads((self.env.directory / 'source-files.json').read_text())),
                         {'code.ts', 'internal.ts', '.env.example'})
        self.assertFalse((self.env.source / 'internal.ts').is_symlink())
        self.assertFalse(self.env.snapshot())
        (self.root / 'code.ts').write_text('edited')
        self.assertTrue(self.env.snapshot())
        self.assertEqual((self.env.source / 'code.ts').read_text(), 'edited')

    def test_test_database_override_preserves_preview_version(self):
        self.env.recipe = {'db': 'postgres:17', 'test_db': 'postgres:15', 'port': 5173, 'start': 'true'}
        self.env.testing = False
        self.env.compose()
        preview = json.loads((self.env.directory / 'compose.json').read_text())
        self.assertEqual(preview['services']['db']['image'], 'postgres:17')
        self.env.testing = True
        self.env.compose()
        testing = json.loads((self.env.directory / 'compose.json').read_text())
        self.assertEqual(testing['services']['db']['image'], 'postgres:15')
        self.assertIn('tmpfs', testing['services']['db'])

    def test_removed_source_does_not_delete_generated_files(self):
        (self.root / 'source.ts').write_text('source')
        self.env.snapshot()
        (self.env.source / 'generated').write_text('dependency cache')
        (self.root / 'source.ts').unlink()
        self.env.snapshot()
        self.assertFalse((self.env.source / 'source.ts').exists())
        self.assertTrue((self.env.source / 'generated').exists())

    def test_tracked_spreadsheet_fixture_is_available_but_untracked_sheet_is_not(self):
        (self.root / 'fixture.xlsx').write_text('checked-in test data')
        (self.root / 'private.xlsx').write_text('untracked data')
        subprocess.run(['git', '-C', str(self.root), 'add', 'fixture.xlsx'], check=True)
        self.env.snapshot()
        self.assertTrue((self.env.source / 'fixture.xlsx').exists())
        self.assertFalse((self.env.source / 'private.xlsx').exists())

    def test_sandbox_cannot_redirect_copy_through_symlink(self):
        (self.root / 'code.ts').write_text('source')
        external = self.base / 'outside'
        external.write_text('untouched')
        (self.env.source / 'code.ts').symlink_to(external)
        self.env.snapshot()
        self.assertEqual(external.read_text(), 'untouched')
        (self.root / 'folder').mkdir()
        (self.root / 'folder/file.ts').write_text('source')
        (self.env.source / 'folder').symlink_to(self.base)
        with self.assertRaises(ValueError):
            self.env.snapshot()

    def test_container_variables_are_not_expanded_by_compose(self):
        env = dev.Environment(self.root, 'augr')
        env.compose()
        config = json.loads(env.file.read_text())
        self.assertIn('$$DATABASE_URL', str(config['services']['app']['command']))

    def test_worktrees_and_test_stacks_have_distinct_storage(self):
        other = dev.Environment(self.base / 'another-checkout', 'dash')
        test = dev.Environment(self.root, 'dash', test=True)
        self.assertEqual(len({self.env.project, other.project, test.project}), 3)
        for env in [self.env, test]:
            env.compose()
            config = json.loads(env.file.read_text())
            self.assertTrue(config['networks']['default']['internal'])
            self.assertEqual(config['networks']['default']['driver_opts']['com.docker.network.bridge.gateway_mode_ipv4'], 'isolated')
            self.assertNotIn('ports', config['services']['app'])
            self.assertRegex(config['services']['preview']['ports'][0], r'^127\.0\.0\.1:\d+:8080$')
            self.assertNotIn('DATABASE_URL', config['services']['checks']['environment'])
            self.assertNotIn('PROMETHEUS_URL', config['services']['checks']['environment'])
            for service in config['services'].values():
                self.assertNotIn('/var/run/docker.sock', str(service))
            self.assertNotIn(str(self.root) + ':', str(config))
        self.assertIn('tmpfs', json.loads(test.file.read_text())['services']['db'])


class StaleStackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.state = patch.object(dev, 'STATE', self.base / 'state')
        self.state.start()
        self.live = self.base / 'live-worktree'
        self.live.mkdir()
        for project, source in [('t3dev-dash-live', self.live), ('t3dev-clpr-gone', self.base / 'deleted'),
                                ('t3dev-dash-running', self.base / 'deleted-too')]:
            (dev.STATE / project).mkdir(parents=True)
            (dev.STATE / project / 'identity.json').write_text(json.dumps({'source': str(source)}))

    def tearDown(self):
        self.state.stop()
        self.temp.cleanup()

    def docker(self, containers, volumes):
        def fake(argv, **kwargs):
            if argv[1:3] == ['ps', '-a']:
                return subprocess.CompletedProcess(argv, 0, '\n'.join(containers))
            if argv[1:3] == ['volume', 'ls']:
                return subprocess.CompletedProcess(argv, 0, '\n'.join(volumes))
            raise AssertionError(f'unexpected docker call {argv}')
        return fake

    def test_only_unowned_stopped_stacks_are_stale(self):
        containers = ['t3dev-dash-live\texited', 't3dev-clpr-gone\texited', 't3dev-clpr-gone\tcreated',
                      't3dev-dash-running\trunning', 't3dev-dash-abc-test\texited', 'unrelated\texited',
                      't3dev-augr-noidentity\texited']
        volumes = ['t3dev-dash-orphanvol', 'production_db']
        with patch.object(dev, 'run', side_effect=self.docker(containers, volumes)):
            stale, unknown = dev.find_stale_projects()
        self.assertEqual(set(stale), {'t3dev-clpr-gone', 't3dev-dash-abc-test'})
        self.assertEqual(set(unknown), {'t3dev-augr-noidentity', 't3dev-dash-orphanvol'})

    def test_remove_project_scopes_by_label_and_keeps_volumes_unless_requested(self):
        calls = []
        def fake(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, 'id1\n' if argv[-1].startswith('label=') else '')
        with patch.object(dev, 'run', side_effect=fake):
            dev.remove_project('t3dev-clpr-gone', volumes=False)
        removals = [c for c in calls if 'rm' in c]
        self.assertEqual(removals, [['docker', 'rm', 'id1'], ['docker', 'network', 'rm', 'id1']])
        for call in calls:
            if 'rm' not in call:
                self.assertEqual(call[-1], 'label=com.docker.compose.project=t3dev-clpr-gone')
        calls.clear()
        with patch.object(dev, 'run', side_effect=fake):
            dev.remove_project('t3dev-clpr-gone', volumes=True)
        self.assertIn(['docker', 'volume', 'rm', 'id1'], calls)
        self.assertNotIn('-f', [arg for call in calls for arg in call])

    def test_gc_reports_without_apply_and_removes_volumes_with_apply(self):
        stale = ({'t3dev-clpr-gone': 'worktree missing'}, [])
        with patch.object(dev, 'find_stale_projects', return_value=stale), \
             patch.object(dev, 'remove_project') as remove, patch('sys.stdout', new_callable=io.StringIO) as output:
            dev.gc()
            remove.assert_not_called()
            self.assertIn('Stale: t3dev-clpr-gone', output.getvalue())
            dev.gc(apply=True)
            remove.assert_called_once_with('t3dev-clpr-gone', volumes=True)

    def test_start_removes_containers_of_deleted_worktrees_but_keeps_volumes(self):
        env = dev.Environment(self.live, 'dash')
        stale = ({'t3dev-clpr-gone': 'worktree missing', 't3dev-dash-x-test': 'leftover test stack'}, [])
        with patch.object(dev, 'find_stale_projects', return_value=stale), \
             patch.object(dev, 'remove_project') as remove, \
             patch.object(dev, 'run', return_value=subprocess.CompletedProcess([], 0, 't3dev-a\nt3dev-b\n')), \
             patch('sys.stderr', new_callable=io.StringIO):
            with self.assertRaisesRegex(ValueError, 'Host limit'):
                env.start()
        remove.assert_called_once_with('t3dev-clpr-gone', volumes=False)


class TeardownTests(unittest.TestCase):
    def test_sigterm_runs_finally_blocks(self):
        script = (
            'import os, signal, sys, dev\n'
            'signal.signal(signal.SIGTERM, dev._terminate)\n'
            'try:\n'
            '    os.kill(os.getpid(), signal.SIGTERM)\n'
            'finally:\n'
            '    print("teardown ran")\n')
        result = subprocess.run([sys.executable, '-c', script], cwd=Path(dev.__file__).parent,
                                capture_output=True, text=True)
        self.assertIn('teardown ran', result.stdout)
        self.assertEqual(result.returncode, 128 + signal.SIGTERM)


class LayoutTests(unittest.TestCase):
    def test_hasanara_selects_backend_or_frontend_layout_from_checkout(self):
        legacy = next(l['recipe'] for l in dev.PROFILES['hasanara']['layouts'] if l['when'] == 'frontend/package.json')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(dev, 'STATE', root / 'state'):
                headless = dev.Environment(root, 'hasanara')
                self.assertNotIn('layouts', headless.recipe)
                self.assertEqual(headless.recipe['health'], '/health')
                for action in ['setup', 'start', 'test', 'verify']:
                    self.assertNotIn('frontend', headless.recipe[action])
                    self.assertNotIn('npm', headless.recipe[action])
                self.assertNotIn(' & ', headless.recipe['start'])
                self.assertIn(f"--port {headless.recipe['port']}", headless.recipe['start'])
                self.assertIn('run_migrations.py upgrade', headless.recipe['test'])
                (root / 'frontend').mkdir()
                (root / 'frontend/package.json').write_text('{}')
                frontend = dev.Environment(root, 'hasanara')
                for key, value in legacy.items():
                    self.assertEqual(frontend.recipe[key], value)
                self.assertEqual(frontend.recipe['health'], '/api/health')
                self.assertTrue(frontend.recipe['setup'].startswith('npm --prefix frontend ci'))
                self.assertTrue(frontend.recipe['setup'].endswith(headless.recipe['setup']))
                for env in [headless, frontend]:
                    self.assertEqual(env.recipe['env'], dev.PROFILES['hasanara']['env'])
                    self.assertEqual(env.recipe['test_env'], dev.PROFILES['hasanara']['test_env'])

    def test_hasanara_deployment_checkout_runs_core_from_submodule(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'frontend').mkdir()
            (root / 'frontend/package.json').write_text('{}')
            (root / 'core').mkdir()
            (root / 'core/constraints.txt').write_text('')
            with patch.object(dev, 'STATE', root / 'state'):
                recipe = dev.Environment(root, 'hasanara').recipe
            self.assertIn('-c core/constraints.txt -r core/requirements-api.txt', recipe['setup'])
            self.assertTrue(recipe['start'].startswith('(cd core && '))
            self.assertIn('--port 41177) & cd frontend;', recipe['start'])
            self.assertIn('npm --prefix frontend run api:check', recipe['verify'])
            self.assertNotIn('scripts/validate.py', recipe['verify'])
            self.assertNotIn('pytest', recipe['test'] + recipe['verify'])
            self.assertEqual(recipe['health'], '/api/health')

    def test_snapshot_includes_submodule_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            git = ['git', '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', '-c', 'protocol.file.allow=always']
            core = base / 'core-src'
            core.mkdir()
            subprocess.run(['git', 'init', '-q', str(core)], check=True)
            (core / 'constraints.txt').write_text('x==1\n')
            subprocess.run([*git, '-C', str(core), 'add', '.'], check=True)
            subprocess.run([*git, '-C', str(core), 'commit', '-qm', 'core'], check=True)
            root = base / 'deploy'
            root.mkdir()
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            subprocess.run([*git, '-C', str(root), 'submodule', 'add', '-q', str(core), 'core'], check=True)
            subprocess.run([*git, '-C', str(root), 'commit', '-qm', 'deploy'], check=True)
            with patch.object(dev, 'STATE', base / 'state'):
                env = dev.Environment(root, 'hasanara')
                env.snapshot()
            self.assertEqual((env.source / 'core/constraints.txt').read_text(), 'x==1\n')

    def test_profiles_without_layouts_are_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(dev, 'STATE', Path(temporary) / 'state'):
                self.assertEqual(dev.Environment(Path(temporary), 'dash').recipe, dev.PROFILES['dash'])


if __name__ == '__main__':
    unittest.main()


class TestBackendTests(unittest.TestCase):
    def test_vm_backend_applies_only_to_disposable_tests(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            shared = base / 'shared'
            shared.mkdir()
            config = base / 'backend.json'
            config.write_text(json.dumps({'context': 'kuznya', 'snapshot_root': str(shared)}))
            with patch.object(dev, 'TEST_BACKEND', config), patch.object(dev, 'STATE', base / 'host'):
                preview = dev.Environment(base, 'dash')
                test = dev.Environment(base, 'dash', test=True)
                self.assertEqual(preview.docker, ['docker'])
                self.assertEqual(preview.directory.parent, base / 'host')
                self.assertEqual(test.docker, ['docker', '--context', 'kuznya'])
                self.assertEqual(test.directory.parent, shared)
                test.file.write_text('{}')
                with patch.object(dev, 'compose_run') as compose:
                    test.dc('down')
                    self.assertEqual(compose.call_args.args[0][:4], ['docker', '--context', 'kuznya', 'compose'])

    def test_missing_vm_share_fails_without_host_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = base / 'backend.json'
            config.write_text(json.dumps({'context': 'kuznya', 'snapshot_root': str(base / 'missing')}))
            with patch.object(dev, 'TEST_BACKEND', config):
                with self.assertRaisesRegex(ValueError, 'unavailable'):
                    dev.Environment(base, 'dash', test=True)

    def test_remote_pool_diagnostic_stays_on_selected_daemon(self):
        failure = subprocess.CompletedProcess([], 17, '', 'all predefined address pools have been fully subnetted')
        with patch.object(dev, 'run', return_value=failure), patch.object(dev, 'report_address_pool_exhaustion') as report:
            dev.compose_run(['docker', '--context', 'kuznya', 'compose', 'up'], capture=True, check=False)
            report.assert_called_once_with(['docker', '--context', 'kuznya'])
