import unittest

from ride_converge.core import Options, _candidate_points, find_convergence
from ride_converge.models import Place, Point, Rider, Route


class FakeProvider:
    def __init__(self):
        self.destination = Point(10, 0)
        self.route_calls = 0

    def reverse_geocode(self, point):
        return f"route-{point.lng:.1f}"

    def nearby_places(self, point, *, radius_m=500, keyword=None, limit=10):
        if 3.5 <= point.lng <= 5.5:
            return [Place("汇流公园东门", Point(4.2, 0), "测试路1号", "公园", "poi-1")]
        return []

    def bicycle_route(self, origin, destination):
        self.route_calls += 1
        # Natural routes merge around x=4 and destination follows the shared x-axis.
        if destination == self.destination:
            d = max(0, (10 - origin.lng)) * 1000
            if origin.lng == 0:
                poly = [origin, Point(2, 0.8), Point(4, 0), destination]
            elif origin.lng == 2:
                poly = [origin, Point(3, -0.8), Point(4, 0), destination]
            else:
                poly = [origin, destination]
            return Route(d, d / 4, poly)

        dx = abs(destination.lng - origin.lng) * 1000
        penalty = 0
        if destination.lng < 4:
            if origin.lng == 0 and destination.lat < 0:
                penalty = 2500
            if origin.lng == 2 and destination.lat > 0:
                penalty = 2500
        d = dx + penalty
        return Route(d, d / 4, [origin, destination])


class CoreTests(unittest.TestCase):
    def test_corridor_candidates_prioritize_early_shared_zone(self):
        p = FakeProvider()
        routes = [
            p.bicycle_route(Point(0, 0), p.destination),
            p.bicycle_route(Point(2, -0.8), p.destination),
        ]
        candidates = _candidate_points(
            routes,
            p.destination,
            Options(
                route_corridor_m=50_000,
                sample_spacing_m=100_000,
                dedupe_radius_m=1,
                zone_radius_m=1,
                max_candidates=20,
            ),
        )
        self.assertTrue(candidates)
        self.assertGreater(candidates[0].shared_remaining_floor_m, candidates[-1].shared_remaining_floor_m)

    def test_prefers_early_feasible_shared_route(self):
        p = FakeProvider()
        riders = [Rider("A", Point(0, 0)), Rider("B", Point(2, -0.8))]
        results = find_convergence(
            p,
            riders,
            p.destination,
            Options(
                max_detour_ratio=0.20,
                route_corridor_m=120_000,
                sample_spacing_m=50_000,
                dedupe_radius_m=1,
                zone_radius_m=1,
                max_candidates=50,
                validation_candidates=20,
                top_n=3,
                snap_to_poi=False,
            ),
        )
        self.assertTrue(results)
        self.assertGreaterEqual(results[0].shared_distance_m, 5500)
        self.assertLessEqual(results[0].max_detour_ratio, 0.20)
        self.assertIsNotNone(results[0].natural_shared_floor_m)

    def test_validation_budget_caps_expensive_candidate_routing(self):
        p = FakeProvider()
        riders = [Rider("A", Point(0, 0)), Rider("B", Point(2, -0.8))]
        find_convergence(
            p,
            riders,
            p.destination,
            Options(
                max_detour_ratio=0.50,
                route_corridor_m=120_000,
                sample_spacing_m=50_000,
                dedupe_radius_m=1,
                zone_radius_m=1,
                max_candidates=50,
                validation_candidates=2,
                top_n=1,
                snap_to_poi=False,
            ),
        )
        # 2 direct routes + at most 2 candidates * (1 shared + 2 riders)
        self.assertLessEqual(p.route_calls, 8)

    def test_snaps_to_real_poi_and_revalidates_routes(self):
        p = FakeProvider()
        riders = [Rider("A", Point(0, 0)), Rider("B", Point(2, -0.8))]
        results = find_convergence(
            p,
            riders,
            p.destination,
            Options(
                max_detour_ratio=0.20,
                route_corridor_m=120_000,
                sample_spacing_m=50_000,
                dedupe_radius_m=1,
                zone_radius_m=1,
                max_candidates=50,
                validation_candidates=20,
                top_n=3,
                snap_to_poi=True,
                poi_keywords=("公园",),
            ),
        )
        self.assertTrue(results)
        self.assertTrue(results[0].is_poi)
        self.assertEqual(results[0].label, "汇流公园东门")
        self.assertLessEqual(results[0].max_detour_ratio, 0.20)

    def test_rejects_single_rider(self):
        p = FakeProvider()
        with self.assertRaises(ValueError):
            find_convergence(p, [Rider("A", Point(0, 0))], p.destination)


if __name__ == "__main__":
    unittest.main()

class DirectionAwareCorridorTests(unittest.TestCase):
    def test_rejects_close_but_opposite_direction_routes(self):
        destination = Point(0.02, 0)
        routes = [
            Route(2200, 500, [Point(0, 0), destination]),
            # Spatially close to the first route, but locally traveling west.
            Route(5000, 900, [Point(0.02, 0.0001), Point(0, 0.0001), Point(0, -0.01), Point(0.02, -0.01), destination]),
        ]
        candidates = _candidate_points(
            routes,
            destination,
            Options(
                route_corridor_m=100,
                sample_spacing_m=300,
                dedupe_radius_m=20,
                zone_radius_m=100,
                min_direction_cosine=0.5,
                min_contiguous_shared_m=300,
                direction_scan_step_m=100,
                max_candidates=30,
            ),
        )
        # The nearby westbound section must not be mistaken for a shared eastbound corridor.
        self.assertTrue(all(c.point.lng > 0.017 for c in candidates))

    def test_accepts_same_direction_contiguous_corridor(self):
        destination = Point(0.03, 0)
        routes = [
            Route(3300, 700, [Point(0, 0), destination]),
            Route(3300, 700, [Point(0, 0.0001), Point(0.03, 0.0001)]),
        ]
        candidates = _candidate_points(
            routes,
            destination,
            Options(
                route_corridor_m=100,
                sample_spacing_m=300,
                dedupe_radius_m=20,
                zone_radius_m=100,
                min_direction_cosine=0.8,
                min_contiguous_shared_m=600,
                direction_scan_step_m=100,
                max_candidates=30,
            ),
        )
        self.assertTrue(candidates)
        self.assertGreaterEqual(candidates[0].direction_alignment, 0.8)
        self.assertGreaterEqual(candidates[0].contiguous_shared_m, 600)
