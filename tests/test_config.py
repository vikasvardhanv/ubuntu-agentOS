import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentos.config import Settings


class SettingsTests(unittest.TestCase):
    def test_loads_gateway_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"gateway": {"fallbacks": [], "retries": 4}}))
            with patch.dict(os.environ, {"AGENTOS_CONFIG_FILE": str(path)}, clear=True):
                settings = Settings.load()
            self.assertEqual((), settings.fallbacks)
            self.assertEqual(4, settings.gateway_retries)
