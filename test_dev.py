import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import dev


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


if __name__ == '__main__':
    unittest.main()
