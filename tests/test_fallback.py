import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ride_converge.core import NoFeasibleConvergence
from ride_converge.models import Point, Route
from ride_converge.providers.amap import AMapError
from ride_converge.web.server import RideWebHandler, _point_payload


def place(name, lng):
    return {"address": name, "point": _point_payload(Point(lng, 39.9))}


class FallbackTests(unittest.TestCase):
    def setUp(self):
        self.provider = Mock()
        self.provider.bicycle_route.side_effect = lambda start, end: Route(1000, 300, [start, end])
        self.handler = SimpleNamespace(server=SimpleNamespace(provider=self.provider))
        self.payload = {
            "city": "北京",
            "origins": [{"name": "A", **place("甲起点", 116.1)}, {"name": "B", **place("乙起点", 116.2)}],
            "waypoints": [place("第一途经点", 116.3), place("第二途经点", 116.4)],
            "destination": place("终点", 116.5),
        }

    def fallback(self, empty=False):
        with patch("ride_converge.web.server.find_convergence", **({"return_value": []} if empty else {"side_effect": NoFeasibleConvergence("无可行汇合点")})):
            return RideWebHandler._plan(self.handler, self.payload)

    def test_fallback_meets_at_first_waypoint_and_keeps_chain_order(self):
        response = self.fallback()
        self.assertEqual(response["ranking"], "fallback_first_common_stop")
        result = response["results"][0]
        self.assertEqual(result["label"], "第一途经点")
        self.assertTrue(result["is_fallback"])
        self.assertFalse(result["constraints_satisfied"])
        self.assertIsNone(result["max_detour_ratio"])
        self.assertEqual(result["shared_distance_m"], 2000)
        self.assertEqual(result["riders"][0]["total_via_distance_m"], 3000)
        self.assertEqual([item["address"] for item in result["shared_targets"]], ["第二途经点", "终点"])
        self.assertEqual(result["routes"]["shared_gcj"], [[39.9, 116.3], [39.9, 116.4], [39.9, 116.5]])
        for line in result["routes"]["riders_gcj"]:
            self.assertEqual(line[-1], [39.9, 116.3])
        self.assertEqual(self.provider.bicycle_route.call_count, 4)

    def test_empty_results_also_trigger_fallback(self):
        self.assertTrue(self.fallback(empty=True)["is_fallback"])

    def test_no_waypoints_means_individual_routes_to_destination(self):
        self.payload["waypoints"] = []
        result = self.fallback()["results"][0]
        self.assertEqual(result["label"], "终点")
        self.assertEqual(result["shared_distance_m"], 0)
        self.assertEqual(result["routes"]["shared_gcj"], [])
        self.assertFalse(result["has_shared_route"])
        self.assertIn("没有后续共同路段", result["fallback_instruction"])
        self.assertEqual(self.provider.bicycle_route.call_count, 2)

    def test_identical_places_do_not_request_zero_length_route(self):
        self.payload["origins"][0]["point"] = self.payload["waypoints"][0]["point"]
        self.payload["waypoints"][1]["point"] = self.payload["waypoints"][0]["point"]
        result = self.fallback()["results"][0]
        self.assertEqual(result["riders"][0]["to_meet_distance_m"], 0)
        self.assertEqual(result["shared_distance_m"], 1000)
        for call in self.provider.bicycle_route.call_args_list:
            self.assertNotEqual(*call.args)

    def test_provider_error_is_not_disguised_as_no_feasible_meeting(self):
        with patch("ride_converge.web.server.find_convergence", side_effect=AMapError("服务不可用")):
            with self.assertRaises(AMapError):
                RideWebHandler._plan(self.handler, self.payload)
        self.provider.bicycle_route.assert_not_called()

    def test_unreachable_fallback_leg_is_reported_instead_of_fabricated(self):
        self.provider.bicycle_route.side_effect = AMapError("该路线不可达")
        with self.assertRaises(AMapError):
            self.fallback()

    def test_empty_fallback_polyline_is_rejected(self):
        self.provider.bicycle_route.return_value = Route(1000, 300, [])
        self.provider.bicycle_route.side_effect = None
        with self.assertRaises(AMapError):
            self.fallback()

    def test_existing_recommendations_are_not_replaced(self):
        rider_stats = [SimpleNamespace(name=name, to_meet_distance_m=500) for name in ("A", "B")]
        recommendation = SimpleNamespace(point=Point(116.25, 39.9), label="正常汇合处", address="地址", category=None,
            is_poi=True, riders=rider_stats, max_detour_ratio=.05, arrival_spread_s=100,
            direction_alignment=1, contiguous_shared_m=1000)
        with patch("ride_converge.web.server.find_convergence", return_value=[recommendation]), patch("ride_converge.web.server._fallback_plan_result") as fallback:
            response = RideWebHandler._plan(self.handler, self.payload)
        fallback.assert_not_called()
        self.assertFalse(response["is_fallback"])
        self.assertEqual(response["results"][0]["label"], "正常汇合处")


if __name__ == "__main__":
    unittest.main()
