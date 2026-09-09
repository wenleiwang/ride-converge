import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ride_converge.providers.amap import AMapError, AMapProvider, _read_dotenv_value


class PlaceSearchTests(unittest.TestCase):
    def test_search_returns_multiple_places_and_filters_invalid_coordinates(self):
        provider = AMapProvider(api_key="测试密钥")
        first = {"id": "a", "name": "西单站", "location": "116.37,39.91", "pname": "北京市", "address": "西单北大街"}
        with patch.object(provider, "_get", return_value={"pois": [
            first, {"id": "b", "name": "西单商场", "location": "116.38,39.92", "address": []},
            first, {"name": "无坐标", "location": ""}, {"location": "NaN,39"}, None,
        ]}) as request:
            places = provider.search_places("西单", "北京")
        self.assertEqual([item.name for item in places], ["西单站", "西单商场"])
        self.assertEqual(places[0].address, "北京市西单北大街")
        self.assertEqual(places[1].address, "北京")
        self.assertEqual(request.call_args.args[1]["city_limit"], "true")
        self.assertEqual(request.call_args.args[1]["region"], "北京")

    def test_empty_search_is_an_empty_list(self):
        provider = AMapProvider(api_key="测试密钥")
        with patch.object(provider, "_get", return_value={"pois": []}):
            self.assertEqual(provider.search_places("不存在的地点", "北京"), [])

    def test_network_error_does_not_expose_key(self):
        provider = AMapProvider(api_key="测试密钥")
        with patch("urllib.request.urlopen", side_effect=RuntimeError("https://example.test/?key=测试密钥")):
            with self.assertRaises(AMapError) as caught:
                provider.search_places("西单", "北京")
        self.assertNotIn("测试密钥", str(caught.exception))


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
