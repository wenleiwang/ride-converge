from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from .geometry import (
    dedupe_points,
    direction_cosine,
    direction_unit_vector,
    haversine_m,
    nearest_position_on_polyline,
    point_forward_on_polyline,
    sample_polyline,
)
from .models import ConvergenceResult, Place, Point, Rider, RiderResult, RoutingProvider, Route


@dataclass
class Options:
    max_detour_ratio: float = 0.15
    route_corridor_m: float = 1200.0
    sample_spacing_m: float = 600.0
    dedupe_radius_m: float = 250.0
    zone_radius_m: float = 700.0
    max_candidates: int = 60
    validation_candidates: int = 18
    top_n: int = 5
    snap_to_poi: bool = True
    poi_radius_m: int = 500
    poi_keywords: tuple[str, ...] = ("公园", "广场", "便利店", "咖啡")
    poi_seed_count: int = 6
    poi_per_keyword: int = 3
    poi_max_candidates: int = 16
    min_direction_cosine: float = 0.65
    min_contiguous_shared_m: float = 600.0
    direction_scan_step_m: float = 200.0
    direction_scan_limit_m: float = 5000.0


@dataclass(frozen=True)
class CorridorCandidate:
    point: Point
    corridor_m: float
    shared_remaining_floor_m: float
    remaining_spread_m: float
    support_routes: int
    direction_alignment: float
    contiguous_shared_m: float


class NoFeasibleConvergence(RuntimeError):
    pass


def _minimum_direction_alignment(direct_routes: list[Route], positions: list) -> float:
    vectors = [direction_unit_vector(route.polyline, pos) for route, pos in zip(direct_routes, positions)]
    alignment = 1.0
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            alignment = min(alignment, direction_cosine(vectors[i], vectors[j]))
    return alignment


def _contiguous_shared_length(
    direct_routes: list[Route],
    positions: list,
    *,
    corridor_m: float,
    min_direction_cosine: float,
    scan_step_m: float,
    scan_limit_m: float,
) -> float:
    """Estimate how long all natural routes remain close and same-direction after a candidate."""
    max_possible = min(pos.remaining_m for pos in positions)
    limit = min(max_possible, scan_limit_m)
    if limit <= 0:
        return 0.0
    step = max(25.0, scan_step_m)
    shared = 0.0
    distance = step
    while distance <= limit + 1e-6:
        advanced = [point_forward_on_polyline(route.polyline, pos, distance) for route, pos in zip(direct_routes, positions)]
        points = [x[0] for x in advanced]
        adv_positions = [x[1] for x in advanced]
        max_pair_distance = 0.0
        for i in range(len(points)):
            for j in range(i + 1, len(points)):
                max_pair_distance = max(max_pair_distance, haversine_m(points[i], points[j]))
        if max_pair_distance > corridor_m:
            break
        if _minimum_direction_alignment(direct_routes, adv_positions) < min_direction_cosine:
            break
        shared = distance
        distance += step
    return min(shared, max_possible)


def _candidate_metrics(point: Point, direct_routes: list[Route], options: Options) -> CorridorCandidate | None:
    positions = [nearest_position_on_polyline(point, route.polyline) for route in direct_routes]
    offsets = [p.distance_m for p in positions]
    if max(offsets) > options.route_corridor_m:
        return None
    direction_alignment = _minimum_direction_alignment(direct_routes, positions)
    if direction_alignment < options.min_direction_cosine:
        return None
    if min(p.remaining_m for p in positions) <= 1.0:
        return None
    contiguous_shared_m = _contiguous_shared_length(
        direct_routes,
        positions,
        corridor_m=options.route_corridor_m,
        min_direction_cosine=options.min_direction_cosine,
        scan_step_m=options.direction_scan_step_m,
        scan_limit_m=options.direction_scan_limit_m,
    )
    if contiguous_shared_m < min(options.min_contiguous_shared_m, min(p.remaining_m for p in positions)):
        return None
    remaining = [p.remaining_m for p in positions]
    return CorridorCandidate(
        point=point,
        corridor_m=max(offsets),
        shared_remaining_floor_m=min(remaining),
        remaining_spread_m=max(remaining) - min(remaining),
        support_routes=sum(1 for d in offsets if d <= options.route_corridor_m),
        direction_alignment=direction_alignment,
        contiguous_shared_m=contiguous_shared_m,
    )


def _cluster_corridor_candidates(candidates: list[CorridorCandidate], radius_m: float) -> list[CorridorCandidate]:
    """Collapse dense samples into convergence zones and keep each zone's earliest point."""
    if radius_m <= 0:
        return candidates
    # Earliest common progress first. This makes the first point entering a shared corridor
    # represent the zone instead of letting dozens of later samples consume route calls.
    ranked = sorted(
        candidates,
        key=lambda c: (-c.shared_remaining_floor_m, c.corridor_m, -c.direction_alignment, -c.contiguous_shared_m, c.remaining_spread_m),
    )
    out: list[CorridorCandidate] = []
    for candidate in ranked:
        if all(haversine_m(candidate.point, existing.point) > radius_m for existing in out):
            out.append(candidate)
    return out


def _candidate_points(direct_routes: list[Route], destination: Point, options: Options) -> list[CorridorCandidate]:
    raw: list[Point] = []
    for route in direct_routes:
        raw.extend(sample_polyline(route.polyline, options.sample_spacing_m))
    raw.append(destination)
    raw = dedupe_points(raw, max(20.0, options.dedupe_radius_m / 2))

    compatible: list[CorridorCandidate] = []
    for point in raw:
        candidate = _candidate_metrics(point, direct_routes, options)
        if candidate:
            compatible.append(candidate)

    zones = _cluster_corridor_candidates(compatible, options.zone_radius_m)
    zones.sort(
        key=lambda c: (
            -c.shared_remaining_floor_m,
            c.corridor_m,
            -c.direction_alignment,
            -c.contiguous_shared_m,
            c.remaining_spread_m,
        )
    )
    return zones[: options.max_candidates]


def _evaluate_candidate(
    provider: RoutingProvider,
    riders: list[Rider],
    direct_routes: list[Route],
    destination: Point,
    point: Point,
    corridor_m: float,
    max_detour_ratio: float,
    *,
    place: Place | None = None,
    shared_remaining_floor_m: float | None = None,
    remaining_spread_m: float | None = None,
    direction_alignment: float | None = None,
    contiguous_shared_m: float | None = None,
) -> ConvergenceResult | None:
    shared = provider.bicycle_route(point, destination)
    rider_results: list[RiderResult] = []
    for rider, direct in zip(riders, direct_routes):
        to_meet = provider.bicycle_route(rider.origin, point)
        via = to_meet.distance_m + shared.distance_m
        detour = max(0.0, (via - direct.distance_m) / max(direct.distance_m, 1.0))
        if detour > max_detour_ratio:
            return None
        rider_results.append(
            RiderResult(
                name=rider.name,
                to_meet_distance_m=to_meet.distance_m,
                to_meet_duration_s=to_meet.duration_s,
                total_via_distance_m=via,
                direct_distance_m=direct.distance_m,
                detour_ratio=detour,
            )
        )

    durations = [r.to_meet_duration_s for r in rider_results]
    detours = [r.detour_ratio for r in rider_results]
    label: str | None = None
    address: str | None = None
    category: str | None = None
    if place:
        label, address, category = place.name, place.address, place.category
    else:
        try:
            address = provider.reverse_geocode(point)
            label = address
        except Exception:
            pass

    return ConvergenceResult(
        point=point,
        label=label,
        address=address,
        category=category,
        shared_distance_m=shared.distance_m,
        shared_duration_s=shared.duration_s,
        max_detour_ratio=max(detours),
        avg_detour_ratio=mean(detours),
        arrival_spread_s=max(durations) - min(durations),
        route_corridor_m=corridor_m,
        riders=rider_results,
        is_poi=place is not None,
        natural_shared_floor_m=shared_remaining_floor_m,
        route_remaining_spread_m=remaining_spread_m,
        direction_alignment=direction_alignment,
        contiguous_shared_m=contiguous_shared_m,
    )


def _sort_results(results: list[ConvergenceResult]) -> None:
    results.sort(
        key=lambda x: (
            -x.shared_distance_m,
            x.max_detour_ratio,
            x.arrival_spread_s,
            x.route_corridor_m,
            -(x.direction_alignment if x.direction_alignment is not None else -1.0),
            -(x.contiguous_shared_m if x.contiguous_shared_m is not None else 0.0),
            0 if x.is_poi else 1,
        )
    )


def _snap_to_places(
    provider: RoutingProvider,
    riders: list[Rider],
    direct_routes: list[Route],
    destination: Point,
    raw_results: list[ConvergenceResult],
    options: Options,
) -> list[ConvergenceResult]:
    if not options.snap_to_poi or not hasattr(provider, "nearby_places"):
        return []

    discovered: list[Place] = []
    for seed in raw_results[: options.poi_seed_count]:
        for keyword in options.poi_keywords:
            try:
                places = provider.nearby_places(
                    seed.point,
                    radius_m=options.poi_radius_m,
                    keyword=keyword or None,
                    limit=options.poi_per_keyword,
                )
            except Exception:
                continue
            discovered.extend(places)

    unique: list[Place] = []
    ids: set[str] = set()
    for place in discovered:
        if place.provider_id and place.provider_id in ids:
            continue
        if any(haversine_m(place.point, p.point) <= 40 for p in unique):
            continue
        if place.provider_id:
            ids.add(place.provider_id)
        unique.append(place)

    def seed_distance(place: Place) -> float:
        return min(haversine_m(place.point, r.point) for r in raw_results)

    unique.sort(key=seed_distance)
    unique = unique[: options.poi_max_candidates]

    out: list[ConvergenceResult] = []
    for place in unique:
        candidate = _candidate_metrics(place.point, direct_routes, options)
        if not candidate:
            continue
        result = _evaluate_candidate(
            provider,
            riders,
            direct_routes,
            destination,
            place.point,
            candidate.corridor_m,
            options.max_detour_ratio,
            place=place,
            shared_remaining_floor_m=candidate.shared_remaining_floor_m,
            remaining_spread_m=candidate.remaining_spread_m,
            direction_alignment=candidate.direction_alignment,
            contiguous_shared_m=candidate.contiguous_shared_m,
        )
        if result:
            out.append(result)
    _sort_results(out)
    return out


def find_convergence(
    provider: RoutingProvider,
    riders: list[Rider],
    destination: Point,
    options: Options | None = None,
) -> list[ConvergenceResult]:
    options = options or Options()
    if len(riders) < 2:
        raise ValueError("At least two riders are required")
    if not (0 <= options.max_detour_ratio <= 1):
        raise ValueError("max_detour_ratio must be between 0 and 1")
    if options.validation_candidates < 1:
        raise ValueError("validation_candidates must be >= 1")
    if not (-1 <= options.min_direction_cosine <= 1):
        raise ValueError("min_direction_cosine must be between -1 and 1")
    if options.min_contiguous_shared_m < 0:
        raise ValueError("min_contiguous_shared_m must be >= 0")

    direct_routes = [provider.bicycle_route(r.origin, destination) for r in riders]
    if any(not r.polyline for r in direct_routes):
        raise ValueError("Provider must return route polylines for path-first convergence")

    candidates = _candidate_points(direct_routes, destination, options)
    raw_results: list[ConvergenceResult] = []
    # Spend expensive route calls only on same-direction, contiguous common-corridor zones.
    for candidate in candidates[: options.validation_candidates]:
        result = _evaluate_candidate(
            provider,
            riders,
            direct_routes,
            destination,
            candidate.point,
            candidate.corridor_m,
            options.max_detour_ratio,
            shared_remaining_floor_m=candidate.shared_remaining_floor_m,
            remaining_spread_m=candidate.remaining_spread_m,
            direction_alignment=candidate.direction_alignment,
            contiguous_shared_m=candidate.contiguous_shared_m,
        )
        if result:
            raw_results.append(result)

    if not raw_results:
        raise NoFeasibleConvergence(
            "No convergence point satisfied route direction, contiguous-corridor, and detour constraints. "
            "Try increasing --max-detour/--corridor or relaxing --min-direction-cosine/--min-shared-segment."
        )

    _sort_results(raw_results)
    poi_results = _snap_to_places(provider, riders, direct_routes, destination, raw_results, options)

    if poi_results:
        return poi_results[: options.top_n]
    return raw_results[: options.top_n]
