import unittest
from datetime import datetime

from ride_converge.models import ConvergenceResult, Point, RiderResult
from ride_converge.schedule import plan_departures


def fake_result():
    return ConvergenceResult(
        point=Point(116.4, 39.9),
        label="测试碰头点",
        address=None,
        category=None,
        shared_distance_m=20_000,
        shared_duration_s=3600,
        max_detour_ratio=0.08,
        avg_detour_ratio=0.04,
        arrival_spread_s=600,
        route_corridor_m=500,
        riders=[
            RiderResult("A", 10_000, 1800, 30_000, 29_000, 0.034),
            RiderResult("B", 8_000, 1200, 28_000, 27_000, 0.037),
        ],
    )


class DeparturePlanTests(unittest.TestCase):
    def test_back_calculates_departures_with_buffer(self):
        meet = datetime.fromisoformat("2026-09-05T09:15:00")
        plan = plan_departures(fake_result(), meet, buffer_s=180, uncertainty_ratio=0, minimum_uncertainty_s=0)
        by_name = {x.name: x for x in plan.riders}
        self.assertEqual(by_name["A"].expected_arrival_at.isoformat(), "2026-09-05T09:12:00")
        self.assertEqual(by_name["A"].recommended_departure_at.isoformat(), "2026-09-05T08:42:00")
        self.assertEqual(by_name["B"].recommended_departure_at.isoformat(), "2026-09-05T08:52:00")
        self.assertEqual(plan.departure_spread_s, 600)

    def test_planning_allowance_moves_latest_safe_departure_earlier(self):
        meet = datetime.fromisoformat("2026-09-05T09:15:00")
        plan = plan_departures(fake_result(), meet, buffer_s=0, uncertainty_ratio=0.10, minimum_uncertainty_s=120)
        by_name = {x.name: x for x in plan.riders}
        # A ride is 30 minutes, so 10% = 3 minutes.
        self.assertEqual(by_name["A"].uncertainty_s, 180)
        self.assertEqual(by_name["A"].latest_safe_departure_at.isoformat(), "2026-09-05T08:42:00")
        # B ride is 20 minutes, minimum allowance wins at 2 minutes.
        self.assertEqual(by_name["B"].uncertainty_s, 120)
        self.assertEqual(by_name["B"].latest_safe_departure_at.isoformat(), "2026-09-05T08:53:00")

    def test_rejects_negative_buffer(self):
        with self.assertRaises(ValueError):
            plan_departures(fake_result(), datetime.now(), buffer_s=-1)


if __name__ == "__main__":
    unittest.main()
