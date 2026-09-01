from __future__ import annotations

import math
from dataclasses import dataclass

from .models import Point

EARTH_RADIUS_M = 6_371_008.8


@dataclass(frozen=True)
class PolylinePosition:
    distance_m: float
    remaining_m: float
    segment_index: int
    segment_fraction: float
    nearest: Point


def direction_unit_vector(polyline: list[Point], position: PolylinePosition) -> tuple[float, float]:
    """以单位向量形式返回路线在当前位置的前进方向。"""
    if len(polyline) < 2 or position.segment_index < 0:
        return (0.0, 0.0)
    i = min(position.segment_index, len(polyline) - 2)
    a, b = polyline[i], polyline[i + 1]
    ref_lat = (a.lat + b.lat) / 2.0
    ax, ay = _xy_m(a, ref_lat)
    bx, by = _xy_m(b, ref_lat)
    vx, vy = bx - ax, by - ay
    norm = math.hypot(vx, vy)
    if norm == 0:
        return (0.0, 0.0)
    return (vx / norm, vy / norm)


def direction_cosine(a: tuple[float, float], b: tuple[float, float]) -> float:
    if a == (0.0, 0.0) or b == (0.0, 0.0):
        return -1.0
    return max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1]))


def point_forward_on_polyline(
    polyline: list[Point], position: PolylinePosition, distance_m: float
) -> tuple[Point, PolylinePosition]:
    """从投影位置沿路线折线向前移动指定米数。"""
    if not polyline:
        raise ValueError('polyline 不能为空')
    if len(polyline) == 1 or distance_m <= 0:
        return position.nearest, position

    i = min(max(position.segment_index, 0), len(polyline) - 2)
    current = position.nearest
    remaining = distance_m
    fraction = position.segment_fraction
    while i < len(polyline) - 1:
        target = polyline[i + 1]
        seg_left = haversine_m(current, target)
        if remaining <= seg_left or seg_left == 0:
            if seg_left == 0:
                current = target
                i += 1
                fraction = 0.0
                continue
            t = remaining / seg_left
            point = Point(
                lng=current.lng + t * (target.lng - current.lng),
                lat=current.lat + t * (target.lat - current.lat),
            )
            return point, nearest_position_on_polyline(point, polyline)
        remaining -= seg_left
        current = target
        i += 1
        fraction = 0.0
    end = polyline[-1]
    return end, nearest_position_on_polyline(end, polyline)


def haversine_m(a: Point, b: Point) -> float:
    p1 = math.radians(a.lat)
    p2 = math.radians(b.lat)
    dp = math.radians(b.lat - a.lat)
    dl = math.radians(b.lng - a.lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def _xy_m(point: Point, ref_lat: float) -> tuple[float, float]:
    """将经纬度投影到以米为单位的局部等距圆柱平面。"""
    lat_r = math.radians(point.lat)
    lng_r = math.radians(point.lng)
    ref_r = math.radians(ref_lat)
    return EARTH_RADIUS_M * lng_r * math.cos(ref_r), EARTH_RADIUS_M * lat_r


def nearest_position_on_polyline(point: Point, polyline: list[Point]) -> PolylinePosition:
    """返回近似精确的线段投影以及路线折线的剩余距离。

    局部等距圆柱投影对于城市级路线走廊已足够精确，
    并且明显优于仅与路线折线顶点比较的方式。
    """
    if not polyline:
        return PolylinePosition(float("inf"), float("inf"), -1, 0.0, point)
    if len(polyline) == 1:
        return PolylinePosition(haversine_m(point, polyline[0]), 0.0, 0, 0.0, polyline[0])

    seg_lengths = [haversine_m(a, b) for a, b in zip(polyline, polyline[1:])]
    suffix = [0.0] * len(polyline)
    for i in range(len(seg_lengths) - 1, -1, -1):
        suffix[i] = suffix[i + 1] + seg_lengths[i]

    best: PolylinePosition | None = None
    for i, (a, b) in enumerate(zip(polyline, polyline[1:])):
        ref_lat = (a.lat + b.lat + point.lat) / 3.0
        ax, ay = _xy_m(a, ref_lat)
        bx, by = _xy_m(b, ref_lat)
        px, py = _xy_m(point, ref_lat)
        vx, vy = bx - ax, by - ay
        denom = vx * vx + vy * vy
        t = 0.0 if denom == 0 else ((px - ax) * vx + (py - ay) * vy) / denom
        t = max(0.0, min(1.0, t))
        nx, ny = ax + t * vx, ay + t * vy
        distance = math.hypot(px - nx, py - ny)
        nearest = Point(
            lng=a.lng + t * (b.lng - a.lng),
            lat=a.lat + t * (b.lat - a.lat),
        )
        remaining = (1.0 - t) * seg_lengths[i] + suffix[i + 1]
        pos = PolylinePosition(distance, remaining, i, t, nearest)
        if best is None or pos.distance_m < best.distance_m:
            best = pos
    assert best is not None
    return best


def min_distance_to_polyline_points(point: Point, polyline: list[Point]) -> float:
    # 为保持 API 兼容性而保留；v0.3 起内部使用线段投影。
    return nearest_position_on_polyline(point, polyline).distance_m


def sample_polyline(polyline: list[Point], spacing_m: float = 1200.0) -> list[Point]:
    """以大致均匀的米制间距对路线采样，并包含两个端点。"""
    if len(polyline) <= 1 or spacing_m <= 0:
        return list(polyline)

    out = [polyline[0]]
    distance_since_sample = 0.0
    current = polyline[0]

    for target in polyline[1:]:
        seg_start = current
        seg_remaining = haversine_m(seg_start, target)
        if seg_remaining == 0:
            current = target
            continue

        while distance_since_sample + seg_remaining >= spacing_m:
            needed = spacing_m - distance_since_sample
            fraction = needed / seg_remaining
            sample = Point(
                lng=seg_start.lng + fraction * (target.lng - seg_start.lng),
                lat=seg_start.lat + fraction * (target.lat - seg_start.lat),
            )
            out.append(sample)
            seg_start = sample
            seg_remaining = haversine_m(seg_start, target)
            distance_since_sample = 0.0
        distance_since_sample += seg_remaining
        current = target

    if haversine_m(out[-1], polyline[-1]) > 20:
        out.append(polyline[-1])
    return out


def dedupe_points(points: list[Point], radius_m: float = 250.0) -> list[Point]:
    out: list[Point] = []
    for p in points:
        if all(haversine_m(p, q) > radius_m for q in out):
            out.append(p)
    return out
