from __future__ import annotations

import argparse
import json
from datetime import datetime

from .core import Options, find_convergence
from .models import Rider
from .providers.amap import AMapProvider
from .schedule import plan_departures


def _km(m: float) -> str:
    return f"{m / 1000:.1f} km"


def _mins(s: float) -> str:
    return f"{s / 60:.0f} min"


def main() -> None:
    parser = argparse.ArgumentParser(description="Find a path-first bicycle convergence point")
    parser.add_argument("--city", default="北京")
    parser.add_argument("--origin", action="append", required=True, help='NAME=ADDRESS; repeat for each rider')
    parser.add_argument("--destination", required=True)
    parser.add_argument("--max-detour", type=float, default=0.15, help="Maximum detour ratio, e.g. 0.15")
    parser.add_argument("--corridor", type=float, default=1500, help="Natural-route corridor in meters")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--sample-spacing", type=float, default=600, help="Polyline sampling spacing in meters")
    parser.add_argument("--zone-radius", type=float, default=700, help="Merge nearby common-corridor samples into one zone")
    parser.add_argument("--validation-candidates", type=int, default=18, help="Maximum raw convergence zones to route-validate")
    parser.add_argument(
        "--min-direction-cosine",
        type=float,
        default=0.65,
        help="Minimum forward-direction alignment for natural routes (-1..1; 0.65 is about 49 degrees)",
    )
    parser.add_argument(
        "--min-shared-segment",
        type=float,
        default=600,
        help="Minimum same-direction contiguous natural-route corridor after meetup, in meters",
    )
    parser.add_argument("--no-poi", action="store_true", help="Return route coordinates instead of snapping to nearby POIs")
    parser.add_argument("--poi-radius", type=int, default=500, help="POI search radius around feasible route points")
    parser.add_argument(
        "--poi-keyword",
        action="append",
        help="Preferred meetup POI keyword; repeatable. Defaults: 公园, 广场, 便利店, 咖啡",
    )
    parser.add_argument(
        "--meet-at",
        help="Optional local ISO meetup-ready time, e.g. 2026-09-05T09:15. Back-calculates rider departures.",
    )
    parser.add_argument(
        "--arrival-buffer",
        type=float,
        default=3.0,
        help="Minutes riders should arrive before --meet-at (default: 3)",
    )
    parser.add_argument(
        "--pace-slack",
        type=float,
        default=0.10,
        help="Planning allowance as a fraction of route ETA for latest-safe departure (default: 0.10)",
    )
    parser.add_argument(
        "--min-pace-slack",
        type=float,
        default=2.0,
        help="Minimum planning allowance in minutes for latest-safe departure (default: 2)",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    provider = AMapProvider()
    riders: list[Rider] = []
    for raw in args.origin:
        if "=" not in raw:
            parser.error(f"Invalid origin {raw!r}; expected NAME=ADDRESS")
        name, address = raw.split("=", 1)
        riders.append(Rider(name=name.strip(), origin=provider.geocode(address.strip(), args.city)))
    destination = provider.geocode(args.destination, args.city)

    keywords = tuple(args.poi_keyword) if args.poi_keyword else Options.poi_keywords
    results = find_convergence(
        provider,
        riders,
        destination,
        Options(
            max_detour_ratio=args.max_detour,
            route_corridor_m=args.corridor,
            top_n=args.top,
            sample_spacing_m=args.sample_spacing,
            zone_radius_m=args.zone_radius,
            validation_candidates=args.validation_candidates,
            min_direction_cosine=args.min_direction_cosine,
            min_contiguous_shared_m=args.min_shared_segment,
            snap_to_poi=not args.no_poi,
            poi_radius_m=args.poi_radius,
            poi_keywords=keywords,
        ),
    )

    meetup_at = None
    if args.meet_at:
        try:
            meetup_at = datetime.fromisoformat(args.meet_at)
        except ValueError:
            parser.error("--meet-at must be an ISO local datetime such as 2026-09-05T09:15")
        if args.arrival_buffer < 0:
            parser.error("--arrival-buffer must be >= 0")
        if args.pace_slack < 0:
            parser.error("--pace-slack must be >= 0")
        if args.min_pace_slack < 0:
            parser.error("--min-pace-slack must be >= 0")

    if args.json:
        payload = []
        for r in results:
            schedule = None
            if meetup_at is not None:
                plan = plan_departures(
                    r,
                    meetup_at,
                    buffer_s=args.arrival_buffer * 60,
                    uncertainty_ratio=args.pace_slack,
                    minimum_uncertainty_s=args.min_pace_slack * 60,
                )
                schedule = {
                    "meetup_at": plan.meetup_at.isoformat(),
                    "buffer_s": plan.buffer_s,
                    "uncertainty_ratio": plan.uncertainty_ratio,
                    "minimum_uncertainty_s": plan.minimum_uncertainty_s,
                    "departure_spread_s": plan.departure_spread_s,
                    "riders": [
                        {
                            "name": x.name,
                            "ride_duration_s": x.ride_duration_s,
                            "recommended_departure_at": x.recommended_departure_at.isoformat(),
                            "latest_safe_departure_at": x.latest_safe_departure_at.isoformat(),
                            "expected_arrival_at": x.expected_arrival_at.isoformat(),
                            "buffer_s": x.buffer_s,
                            "planning_allowance_s": x.uncertainty_s,
                        }
                        for x in plan.riders
                    ],
                }
            payload.append({
                "point": {"lng": r.point.lng, "lat": r.point.lat},
                "label": r.label,
                "address": r.address,
                "category": r.category,
                "is_poi": r.is_poi,
                "shared_distance_m": r.shared_distance_m,
                "shared_duration_s": r.shared_duration_s,
                "max_detour_ratio": r.max_detour_ratio,
                "avg_detour_ratio": r.avg_detour_ratio,
                "arrival_spread_s": r.arrival_spread_s,
                "route_corridor_m": r.route_corridor_m,
                "natural_shared_floor_m": r.natural_shared_floor_m,
                "route_remaining_spread_m": r.route_remaining_spread_m,
                "direction_alignment": r.direction_alignment,
                "contiguous_shared_m": r.contiguous_shared_m,
                "riders": [x.__dict__ for x in r.riders],
                "departure_plan": schedule,
            })
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    for i, r in enumerate(results, 1):
        poi = "POI" if r.is_poi else "route point"
        print(f"#{i} {r.label or r.point.amap()} [{poi}]")
        if r.address and r.address != r.label:
            print(f"  address: {r.address}")
        print(f"  shared: {_km(r.shared_distance_m)} / {_mins(r.shared_duration_s)}")
        print(f"  max detour: {r.max_detour_ratio:.1%}; arrival spread: {_mins(r.arrival_spread_s)}")
        if r.natural_shared_floor_m is not None:
            print(f"  natural corridor: {_km(r.natural_shared_floor_m)} remaining; width {r.route_corridor_m:.0f} m")
        if r.direction_alignment is not None and r.contiguous_shared_m is not None:
            print(f"  direction alignment: {r.direction_alignment:.2f}; contiguous shared corridor: {_km(r.contiguous_shared_m)}")
        for rr in r.riders:
            print(f"  - {rr.name}: {_km(rr.to_meet_distance_m)}, {_mins(rr.to_meet_duration_s)}, detour {rr.detour_ratio:.1%}")
        if meetup_at is not None:
            plan = plan_departures(
                r,
                meetup_at,
                buffer_s=args.arrival_buffer * 60,
                uncertainty_ratio=args.pace_slack,
                minimum_uncertainty_s=args.min_pace_slack * 60,
            )
            print(f"  departure sync: ready together at {plan.meetup_at.isoformat(timespec='minutes')}")
            for departure in plan.riders:
                print(
                    f"    - {departure.name}: depart {departure.recommended_departure_at.isoformat(timespec='minutes')} "
                    f"(safer {departure.latest_safe_departure_at.isoformat(timespec='minutes')} with "
                    f"{departure.uncertainty_s / 60:.0f} min planning allowance)"
                )
