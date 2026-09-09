import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from ride_converge.models import Place, Point, Route
from ride_converge.web.server import (
    _join_route_polylines,
    _payload_point,
    _polyline_gcj_payload,
    _point_payload,
    gcj02_to_wgs84,
    wgs84_to_gcj02,
    RideWebHandler,
)


class WebCoordinateTests(unittest.TestCase):
    def test_search_candidates_preserve_all_choices_and_gcj_coordinates(self):
        provider = Mock()
        provider.search_places.return_value = [
            Place("西单站", Point(116.37, 39.91), "地址一", provider_id="1"),
            Place("西单商场", Point(116.38, 39.92), "地址二", provider_id="2"),
        ]
        handler = SimpleNamespace(server=SimpleNamespace(provider=provider))
        result = RideWebHandler._search_places(handler, {"query": "西单", "city": "北京"})
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(result["results"][1]["label"], "西单商场")
        self.assertEqual(result["results"][1]["point"]["gcj"], {"lng": 116.38, "lat": 39.92})
        provider.geocode.assert_not_called()

    def test_gcj_wgs_round_trip_is_close(self):
        original = Point(116.397, 39.908)
        wgs = gcj02_to_wgs84(original)
        restored = wgs84_to_gcj02(wgs)
        self.assertAlmostEqual(restored.lng, original.lng, places=4)
        self.assertAlmostEqual(restored.lat, original.lat, places=4)

    def test_point_payload_preserves_amap_coordinate(self):
        point = Point(116.397, 39.908)
        payload = _point_payload(point)
        self.assertEqual(_payload_point(payload, "测试点"), point)
        self.assertIn("wgs", payload)

    def test_invalid_payload_is_rejected(self):
        with self.assertRaises(ValueError):
            _payload_point({"gcj": {"lng": 500, "lat": 39.9}}, "测试点")

    def test_route_chain_removes_adjacent_duplicate_points(self):
        middle = Point(116.4, 39.9)
        routes = [
            Route(1000, 300, [Point(116.3, 39.9), middle]),
            Route(2000, 600, [middle, Point(116.5, 39.9)]),
        ]
        self.assertEqual(
            _join_route_polylines(routes),
            [Point(116.3, 39.9), middle, Point(116.5, 39.9)],
        )

    def test_gcj_polyline_keeps_amap_coordinates(self):
        points = [Point(116.397, 39.908), Point(116.4, 39.91)]
        self.assertEqual(
            _polyline_gcj_payload(points),
            [[39.908, 116.397], [39.91, 116.4]],
        )


if __name__ == "__main__":
    unittest.main()
