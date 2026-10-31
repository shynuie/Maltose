from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from maltose.paths import application_support, default_config_path, environment_value
from maltose.agent.config import load_cli_defaults
from maltose.agent.cli import build_parser


class ProductPathTests(unittest.TestCase):
    def test_new_config_wins_and_legacy_remains_usable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(default_config_path(root, environ={}), root / 'maltose.toml')
            (root / 'myagent.toml').write_text('[agent]\nbrain="echo"\n')
            self.assertEqual(default_config_path(root, environ={}), root / 'myagent.toml')
            (root / 'maltose.toml').write_text('[agent]\nbrain="taskbrain"\n')
            selected = default_config_path(root, environ={})
            self.assertEqual(selected, root / 'maltose.toml')
            self.assertEqual(load_cli_defaults(selected)['brain'], 'taskbrain')

    def test_environment_override_and_explicit_cli_have_clear_precedence(self):
        root = Path('/example')
        values = {'MYAGENT_CONFIG': 'old.toml', 'MALTOSE_CONFIG': 'new.toml'}
        self.assertEqual(default_config_path(root, environ=values), root / 'new.toml')
        self.assertEqual(environment_value('CONFIG', environ={'MYAGENT_CONFIG': 'old'}), 'old')
        with patch.dict('os.environ', {'MALTOSE_CONFIG': '/new.toml'}):
            self.assertEqual(build_parser().parse_args(['--config', '/explicit.toml']).config, Path('/explicit.toml'))

    def test_config_paths_follow_config_directory_including_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'maltose.toml'
            config.write_text('[taskbrain]\nmemory="data/memory"\n[wake]\nconfig="wake.toml"\n[knowledge]\nqueue="data/knowledge/queue.sqlite3"\n')
            result = load_cli_defaults(config)
            self.assertEqual(result['taskbrain_memory'], root / 'data/memory')
            self.assertEqual(result['wake_config'], root / 'wake.toml')
            self.assertEqual(result['knowledge_queue'], root / 'data/knowledge/queue.sqlite3')
            self.assertFalse((root / 'data').exists())

    def test_data_root_does_not_create_or_import_personal_state(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'state'
            self.assertEqual(application_support(environ={'MYAGENT_DATA_DIR': str(target)}), target)
            self.assertEqual(application_support(environ={'MYAGENT_DATA_DIR': '/old', 'MALTOSE_DATA_DIR': str(target)}), target)
            self.assertFalse(target.exists())
