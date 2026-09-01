from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Point:
    lng: float
    lat: float

    def amap(self) -> str:
        return f"{self.lng:.6f},{self.lat:.6f}"


@dataclass(frozen=True)
class Place:
    name: str
    point: Point
    address: str | None = None
    category: str | None = None
    provider_id: str | None = None


@dataclass
class Route:
    distance_m: float
    duration_s: float
    polyline: list[Point] = field(default_factory=list)


@dataclass
class Rider:
    name: str
    origin: Point


@dataclass
class RiderResult:
    name: str
    to_meet_distance_m: float
    to_meet_duration_s: float
    total_via_distance_m: float
    direct_distance_m: float
    detour_ratio: float


@dataclass
class ConvergenceResult:
    point: Point
    label: str | None
    address: str | None
    category: str | None
    shared_distance_m: float
    shared_duration_s: float
    max_detour_ratio: float
    avg_detour_ratio: float
    arrival_spread_s: float
    route_corridor_m: float
    riders: list[RiderResult]
    is_poi: bool = False
    natural_shared_floor_m: float | None = None
    route_remaining_spread_m: float | None = None
    direction_alignment: float | None = None
    contiguous_shared_m: float | None = None


class RoutingProvider(Protocol):
    def geocode(self, address: str, city: str | None = None) -> Point: ...
    def reverse_geocode(self, point: Point) -> str | None: ...
    def bicycle_route(self, origin: Point, destination: Point) -> Route: ...
    def nearby_places(
        self,
        point: Point,
        *,
        radius_m: int = 500,
        keyword: str | None = None,
        limit: int = 10,
    ) -> list[Place]: ...
