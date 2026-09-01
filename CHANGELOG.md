# Changelog

## 0.5.0

- Add synchronized departure planning for a target meetup-ready time.
- Back-calculate each rider's nominal departure from exact routed time to the selected meetup point.
- Add configurable early-arrival buffer with `--arrival-buffer`.
- Add conservative planning allowance with `--pace-slack` and `--min-pace-slack`.
- Add `departure_plan` to JSON output without changing convergence ranking.
- Export `plan_departures`, `DeparturePlan`, and `RiderDeparture` through the Python API.
- Add departure-planning tests; suite now covers 13 cases.

## 0.4.0

- Add direction-aware route-corridor filtering using local forward segment vectors.
- Reject spatially close natural routes that travel in incompatible/opposite directions.
- Require a configurable contiguous same-direction shared corridor after each candidate.
- Add `--min-direction-cosine` and `--min-shared-segment` CLI controls.
- Expose `direction_alignment` and `contiguous_shared_m` diagnostics in text/JSON output.
- Add opposite-direction and same-direction-continuity tests; suite now covers 10 cases.

## 0.3.0

- Detect common route corridors using point-to-segment projection instead of vertex-only proximity.
- Track remaining natural-route distance for every rider and prioritize the earliest shared corridor.
- Cluster dense samples into convergence zones before expensive routing validation.
- Add `validation_candidates` to bound raw candidate route calls.
- Improve polyline sampling with interpolation at roughly even metric spacing.
- Expose natural-corridor diagnostics in JSON/text output.
- Add geometry and route-budget tests.

## 0.2.0

- Snap feasible route points to nearby real POIs and fully revalidate bicycle routes.
- Add provider request caches and POI controls.
- Improve AMap error handling.

## 0.1.0

- Initial path-first convergence search with detour constraints and AMap bicycle routing.
