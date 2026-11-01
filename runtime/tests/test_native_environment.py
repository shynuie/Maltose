import os
from pathlib import Path
import tempfile
import unittest
from maltose.runtime.environment import load_private_environment, parse_service_credentials


class NativeEnvironmentTests(unittest.TestCase):
    def test_plain_quoted_and_export_values_preserve_credentials_without_shell_execution(self):
        values = parse_service_credentials('''# private fixture
OPENAI_API_KEY=fixture#hash # comment
export BRAVE_SEARCH_API_KEY='quoted # value'
TASKBRAIN_TOKEN="$(echo never-executed)"
''')
        self.assertEqual(values, {'OPENAI_API_KEY': 'fixture#hash', 'BRAVE_SEARCH_API_KEY': 'quoted # value', 'TASKBRAIN_TOKEN': '$(echo never-executed)'})
        for unsafe in ['PATH=/other', 'OPENAI_API_KEY=one\nOPENAI_API_KEY=two', 'OPENAI_API_KEY="unfinished', 'OPENAI_API_KEY=', 'OPENAI_API_KEY=two words']:
            with self.subTest(unsafe=unsafe), self.assertRaises(ValueError): parse_service_credentials(unsafe)

    def test_only_private_regular_file_is_loaded_and_explicit_environment_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            environment = {'OPENAI_API_KEY': 'explicit'}
            load_private_environment(path, environ=environment)
            path.write_text('OPENAI_API_KEY=stored\nBRAVE_SEARCH_API_KEY=fixture')
            path.chmod(0o644)
            with self.assertRaises(PermissionError): load_private_environment(path, environ=environment)
            path.chmod(0o600)
            load_private_environment(path, environ=environment)
            self.assertEqual(environment, {'OPENAI_API_KEY': 'explicit', 'BRAVE_SEARCH_API_KEY': 'fixture'})
            link = Path(directory) / 'link'
            link.symlink_to(path)
            with self.assertRaises(OSError): load_private_environment(link, environ={})
            pipe = Path(directory) / 'pipe'
            os.mkfifo(pipe, 0o600)
            with self.assertRaises(PermissionError): load_private_environment(pipe, environ={})

    def test_invalid_file_is_atomic_and_does_not_leak_values_in_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            secret = 'private-fixture-not-for-errors'
            path.write_text('OPENAI_API_KEY=' + secret + '\nUNSUPPORTED=' + secret)
            path.chmod(0o600)
            environment = {}
            with self.assertRaises(ValueError) as error: load_private_environment(path, environ=environment)
            self.assertNotIn(secret, str(error.exception))
            self.assertEqual(environment, {})
