import unittest
from ai.local_chat import LocalChatProvider, LocalChatConfig, load_local_config
from ai.models import ProviderError


class LocalChatTests(unittest.TestCase):
    def test_invalid_input_does_not_contact_server(self):
        self.assertEqual(LocalChatProvider(LocalChatConfig()).chat(' ').error_id, 'AI_INVALID_INPUT')

    def test_port_validation(self):
        with self.assertRaises(ValueError):
            load_local_config({'JARVIS_LOCAL_PORT': '8080/path'})

    def test_timeout_validation(self):
        with self.assertRaises(ValueError):
            load_local_config({'JARVIS_LOCAL_TIMEOUT': '999'})


if __name__ == '__main__':
    unittest.main()
