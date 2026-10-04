import json
import io
from pathlib import Path
import subprocess
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


class LayoutTests(unittest.TestCase):
    def test_hasanara_selects_backend_or_frontend_layout_from_checkout(self):
        legacy = dev.PROFILES['hasanara']['layouts'][0]['recipe']
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
