# Algorithm reference

## Problem

Given riders with origins `S_i` and a common destination `D`, find an early practical convergence point `M` that stays close to the riders' natural bicycle routes and leaves a long shared ride `M -> D`.

The project is intentionally **path-first**: route compatibility and detour limits are hard constraints, not cosmetic score terms.

## 1. Direct-route baseline

For every rider, fetch the provider's recommended bicycle route:

`R_i = route(S_i, D)`

Keep distance, duration, and polyline. These routes define what "not meaningfully out of the way" means for each rider.

## 2. Direction-aware common-corridor detection (v0.4)

v0.4 samples the direct-route polylines at approximately even metric spacing. For every sampled point, it projects that point onto **every route segment**, rather than merely comparing it with route vertices.

For route `R_i`, the projection yields:

- `offset_i`: distance from candidate to the nearest route segment;
- `remaining_i`: distance along that natural route from the projected position to `D`.

A point belongs to the common corridor only when:

`max(offset_i) <= route_corridor_m`

For each surviving point we record:

`shared_remaining_floor = min(remaining_i)`

This conservative value estimates how much natural route remains for **all** riders once they reach that corridor location.

We also record:

`remaining_spread = max(remaining_i) - min(remaining_i)`

A small spread means the point represents roughly the same stage of the trip on every rider's natural route.

### Direction compatibility

Spatial proximity alone is insufficient. For each projected route position, v0.4 computes the local **forward** segment unit vector. For every pair of riders it measures the cosine similarity:

`alignment(i,j) = dot(direction_i, direction_j)`

Interpretation:

- `1.0`: same direction;
- `0.0`: perpendicular;
- `-1.0`: opposite direction.

A candidate is rejected when the minimum pairwise alignment is below `min_direction_cosine` (default `0.65`, roughly a 49-degree maximum disagreement). This prevents an opposite-flow road from looking like a shared corridor merely because it is nearby.

### Contiguous shared segment

A single same-direction point can still be a transient crossing. v0.4 therefore advances forward along every natural route in metric steps. At every step:

1. the advanced route positions must remain within `route_corridor_m`; and
2. their forward directions must still satisfy `min_direction_cosine`.

The verified length is recorded as `contiguous_shared_m`. A candidate is rejected unless this persists for at least `min_contiguous_shared_m` (default `600 m`).

This is still a geometric/navigation-polyline inference, not a claim that the provider exposes an identical physical road-segment ID. Exact routing through the meetup point remains the final detour validation.

## 3. Convergence zones

Dense neighboring common-corridor samples are clustered using `zone_radius_m`. Within each zone, the earliest compatible point is retained.

This has two benefits:

1. it represents the **first entry into a shared corridor** instead of returning many nearly identical later points;
2. it dramatically reduces expensive route API validation calls.

Zones are pre-ranked by:

1. larger `shared_remaining_floor`;
2. smaller route-corridor width;
3. stronger direction alignment;
4. longer contiguous shared corridor;
5. smaller natural-route remaining-distance spread.

Only the first `validation_candidates` zones are sent to exact navigation validation.

## 4. Exact detour validation

For each candidate `M`, fetch:

- `route(M, D)` once;
- `route(S_i, M)` for every rider.

For rider `i`:

`via_i = distance(S_i, M) + distance(M, D)`

`detour_i = max(0, (via_i - direct_i) / direct_i)`

Reject `M` if any:

`detour_i > max_detour_ratio`

This remains the hard safety rail against geometrically plausible but practically bad meeting points.

## 5. Final ranking

All remaining candidates already satisfy route and detour constraints. Rank lexicographically:

1. larger actual `distance(M, D)` — maximize the shared ride;
2. smaller maximum rider detour;
3. smaller arrival-duration spread;
4. smaller route-corridor width;
5. stronger direction alignment;
6. longer contiguous shared corridor;
7. named POI preferred over a raw route coordinate on ties.

No opaque weighted score is required.

## 6. Practical POI snapping

A mathematically good coordinate may be awkward for a group to stop at. For the best raw convergence points:

1. search nearby POIs;
2. deduplicate close/repeated places;
3. verify that each POI remains in the natural common corridor;
4. re-run all required bicycle routes through that exact POI;
5. re-apply the same detour constraint;
6. rank only the feasible places.

A POI is never merely a renamed coordinate.

## 7. Departure-time synchronization (v0.5)

Departure planning runs **after** a convergence point has been selected, so it does not change route ranking or detour feasibility.

Given a desired local meetup-ready time `T`, an arrival buffer `B`, and exact routed duration `duration_i = route(S_i, M).duration`:

`expected_arrival_i = T - B`

`recommended_departure_i = expected_arrival_i - duration_i`

For a conservative planning suggestion, define:

`planning_allowance_i = max(minimum_slack, duration_i * pace_slack)`

`latest_safe_departure_i = recommended_departure_i - planning_allowance_i`

The planning allowance is intentionally **not** represented as a statistical confidence interval. AMap route duration is treated as an ETA estimate; the extra cushion is controlled by the caller.

All CLI timestamps are interpreted as local ISO datetimes. Time-zone conversion is deliberately outside the routing core; callers that coordinate riders across zones should pass an offset-aware `datetime` through the Python API.

## API-call control

The expensive part is exact route validation. v0.4 therefore separates cheap geometric corridor detection from expensive provider requests.

Approximate raw validation calls are bounded by:

`direct_routes + validation_candidates * (riders + 1)`

before optional POI validation. Providers may additionally cache identical route/geocode/POI requests.

## Current limitations

- Corridor projection uses a local equirectangular approximation, intended for city/regional cycling rather than intercontinental geometry.
- Direction compatibility is inferred from navigation polylines; without provider road-segment IDs it cannot prove that nearby same-direction lines are the exact same physical lane/road.
- Riders are assumed to use the provider's recommended bicycle route.
- POI suitability is category/name based; opening hours and bike parking are not yet considered.
- Departure synchronization uses static route ETA; it does not yet model live speed profiles, rider-specific pace, weather, or traffic uncertainty distributions.

## Candidate future improvements

- persistent route cache;
- explicit route-request budget exposed by providers;
- optional rider-specific pace/speed profiles and dynamic ETA refresh;
- bike-parking / rest-stop preference filters;
- additional map providers.
