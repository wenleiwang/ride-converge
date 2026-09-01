import unittest

from ride_converge.geometry import nearest_position_on_polyline, sample_polyline
from ride_converge.models import Point


class GeometryTests(unittest.TestCase):
    def test_segment_projection_beats_vertex_distance(self):
        route = [Point(0, 0), Point(0.02, 0)]
        query = Point(0.01, 0.001)
        pos = nearest_position_on_polyline(query, route)
        self.assertLess(pos.distance_m, 120)
        self.assertGreater(pos.remaining_m, 1000)
        self.assertLess(pos.remaining_m, 1200)

    def test_even_sampling_interpolates_long_segment(self):
        route = [Point(0, 0), Point(0.03, 0)]
        samples = sample_polyline(route, 1000)
        self.assertGreaterEqual(len(samples), 4)
        self.assertAlmostEqual(samples[0].lng, 0)
        self.assertAlmostEqual(samples[-1].lng, 0.03)


if __name__ == "__main__":
    unittest.main()

class DirectionGeometryTests(unittest.TestCase):
    def test_opposite_direction_vectors_are_negative(self):
        from ride_converge.geometry import direction_cosine, direction_unit_vector
        a = [Point(0, 0), Point(0.01, 0)]
        b = [Point(0.01, 0.0001), Point(0, 0.0001)]
        pa = nearest_position_on_polyline(Point(0.005, 0), a)
        pb = nearest_position_on_polyline(Point(0.005, 0.0001), b)
        self.assertLess(direction_cosine(direction_unit_vector(a, pa), direction_unit_vector(b, pb)), -0.99)
