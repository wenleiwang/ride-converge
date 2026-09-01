import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ride_converge.providers.amap import AMapProvider, _read_dotenv_value


class DotenvTests(unittest.TestCase):
    def test_reads_plain_and_quoted_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text('# 注释\nAMAP_API_KEY="测试密钥"\n', encoding="utf-8")
            self.assertEqual(_read_dotenv_value(path, "AMAP_API_KEY"), "测试密钥")

    def test_provider_uses_dotenv_when_environment_is_unset(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "ride_converge.providers.amap._dotenv_api_key", return_value="测试密钥"
        ):
            provider = AMapProvider()
        self.assertEqual(provider.api_key, "测试密钥")

    def test_explicit_key_has_highest_priority(self):
        with patch.dict(os.environ, {"AMAP_API_KEY": "环境变量密钥"}), patch(
            "ride_converge.providers.amap._dotenv_api_key", return_value="文件密钥"
        ):
            provider = AMapProvider(api_key="显式密钥")
        self.assertEqual(provider.api_key, "显式密钥")


if __name__ == "__main__":
    unittest.main()
