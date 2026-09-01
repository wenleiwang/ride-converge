# ride-converge

**Path-first meetup planning for cyclists heading to one shared destination.**

Instead of finding a geographic midpoint, `ride-converge` finds an early practical convergence point along the riders' real cycling routes, limits individual detours, and maximizes how far the group can ride together afterward.

```text
A ---------\\
            \\
B -----------● M ===================> D
            /
C ----------/

             <---- shared ride ---->
```

The default optimization is:

> maximize shared cycling distance, subject to route compatibility and a per-rider detour limit.

## Why this is different from a midpoint

A geometric midpoint ignores rivers, ring roads, bicycle restrictions and the actual shape of each rider's route. This project starts from each rider's real bicycle route to the final destination and searches for convergence candidates around those paths.

## v0.5 highlights

- Adds **departure-time synchronization** for a chosen convergence result.
- Accepts a local target time when the group wants to be ready together at the meetup point.
- Back-calculates each rider's departure from the exact routed `origin -> meetup` duration.
- Supports an early-arrival buffer and a separate configurable planning allowance.
- Exposes both the nominal recommended departure and a more conservative `latest_safe_departure_at`.
- Keeps v0.4 direction-aware, contiguous shared-corridor detection and POI revalidation.

## Features

- Real bicycle routing through AMap/Gaode Web Service API.
- Multiple riders and one shared destination.
- Path-first, direction-aware candidate generation from navigation polylines.
- Hard maximum-detour constraint per rider.
- Maximizes the shared `meeting point -> destination` route.
- Arrival-time fairness as a tie-breaker.
- Optional synchronized departure planning for a target meetup-ready time.
- Practical POI snapping with full route re-validation.
- Agent Skills-compatible `SKILL.md`.
- CLI and Python API.
- No third-party Python runtime dependencies.

## Requirements

- Python 3.10+
- An AMap Web Service API key
- Internet access for live routing

```bash
export AMAP_API_KEY="..."
```

Do not commit the key.

## Install

```bash
git clone <your-repo-url>
cd ride-converge
python -m pip install -e .
```

## CLI example

```bash
ride-converge \
  --city 北京 \
  --origin 'A=西二旗地铁站' \
  --origin 'B=望京SOHO' \
  --origin 'C=东直门地铁站' \
  --destination '北京城市副中心三大文化建筑' \
  --max-detour 0.15 \
  --corridor 1500 \
  --top 5
```

Customize meetup POIs:

```bash
ride-converge ... \
  --poi-radius 700 \
  --poi-keyword 公园 \
  --poi-keyword 广场 \
  --poi-keyword 便利店
```

Disable POI snapping:

```bash
ride-converge ... --no-poi
```

Structured output:

```bash
ride-converge ... --json
```

### Departure synchronization

If the group wants to be ready together at a specific local time:

```bash
ride-converge \
  --city 北京 \
  --origin 'A=西二旗地铁站' \
  --origin 'B=望京SOHO' \
  --destination '北京城市副中心三大文化建筑' \
  --meet-at 2026-09-05T09:15 \
  --arrival-buffer 3 \
  --pace-slack 0.10 \
  --min-pace-slack 2
```

`--meet-at` is the time the group wants to be ready at the meetup point. The default 3-minute arrival buffer plans each rider to arrive at 09:12 in this example. `--pace-slack` and `--min-pace-slack` produce an additional conservative departure suggestion; this is a planning cushion, **not** a provider-guaranteed ETA confidence interval.

Example interpretation:

```text
A: depart 08:42 (safer 08:39 with 3 min planning allowance)
B: depart 08:52 (safer 08:50 with 2 min planning allowance)
ready together: 09:15
```

## Python API

```python
from ride_converge import Options, Rider, find_convergence
from ride_converge.providers import AMapProvider

provider = AMapProvider()
riders = [
    Rider("A", provider.geocode("西二旗地铁站", "北京")),
    Rider("B", provider.geocode("望京SOHO", "北京")),
]
destination = provider.geocode("北京城市副中心三大文化建筑", "北京")

results = find_convergence(
    provider,
    riders,
    destination,
    Options(max_detour_ratio=0.15, snap_to_poi=True, top_n=5),
)

print(results[0].label, results[0].shared_distance_m)

from datetime import datetime
from ride_converge import plan_departures

plan = plan_departures(
    results[0],
    datetime.fromisoformat("2026-09-05T09:15"),
    buffer_s=180,
)
for rider in plan.riders:
    print(rider.name, rider.recommended_departure_at)
```

## Optimization model

For rider `i`:

```text
direct_i = route(S_i -> D)
via_i    = route(S_i -> M) + route(M -> D)
detour_i = (via_i - direct_i) / direct_i
```

A candidate is rejected when:

```text
max(detour_i) > configured detour limit
```

Among feasible route-compatible candidates, the sorter prioritizes:

1. maximum shared riding distance `M -> D`;
2. minimum worst-rider detour;
3. minimum rider arrival-time spread;
4. tighter proximity to all natural routes;
5. stronger same-direction / contiguous-corridor evidence on ties.

POI snapping is a second pass. Nearby named places are treated as new candidates and must pass the same route-corridor and detour constraints.

See [`references/ALGORITHM.md`](references/ALGORITHM.md) for details.

## API usage note

A raw candidate evaluation requires roughly `N + 1` route lookups for `N` riders. POI snapping adds another bounded candidate pass. v0.3 uses in-process caching and conservative candidate limits, but a hosted service should still add persistent caching, quotas and per-request budgets.

## Testing

Tests use a deterministic fake router and fake POI search and require no API key:

```bash
python -m unittest discover -s tests -v
```

## Roadmap

- [x] Snap meetup coordinates to useful nearby POIs.
- [x] Segment-projected corridor distance for city/regional routing.
- [ ] Persistent route-response caching.
- [ ] Optional road-segment / bike-lane identity checks where providers expose them.
- [ ] More routing providers.
- [x] Departure-time synchronization.
- [ ] Optional web UI / map visualization.

## License

MIT

## Corridor controls

```bash
ride-converge ... \
  --sample-spacing 600 \
  --zone-radius 700 \
  --validation-candidates 18 \
  --min-direction-cosine 0.65 \
  --min-shared-segment 600
```

- `--sample-spacing`: how densely natural routes are sampled before corridor detection.
- `--zone-radius`: merges nearby common-corridor samples into one convergence zone.
- `--validation-candidates`: caps the number of raw zones that receive expensive exact bicycle-route validation.
- `--min-direction-cosine`: rejects routes whose local forward directions disagree too much. `1` means identical direction, `0` perpendicular, `-1` opposite.
- `--min-shared-segment`: requires the natural routes to remain spatially close and direction-compatible for at least this many meters after the candidate.

Use `--json` to inspect `natural_shared_floor_m`, `route_remaining_spread_m`, `route_corridor_m`, `direction_alignment`, and `contiguous_shared_m`.
