---
name: ride-converge
description: Find an early practical bicycle convergence point for two or more riders who share a final destination. Use when riders want to meet as early as possible while staying close to their natural cycling routes, limiting detours, and maximizing the distance they can ride together afterward. Supports path-first routing with AMap/Gaode.
license: MIT
compatibility: Requires Python 3.10+, network access, and an AMap Web Service API key in AMAP_API_KEY for live routing.
metadata:
  version: "0.5.0"
  provider: "amap"
---

# Ride Converge

Find a route-compatible bicycle convergence point for riders heading to one shared destination.

The objective is **not** to find a geometric midpoint. The objective is to find the earliest practical place where riders' natural routes can converge without forcing excessive detours, so the group has as much shared riding as possible after meeting.

## When to use

Use this skill when the user provides or can provide:

- two or more rider origins;
- one shared cycling destination;
- a desire to meet before the destination;
- bicycle routing as the preferred mode.

Typical requests include:

- "我们从不同地方出发，最后骑去十三陵，找一个尽量早汇合的点。"
- "不要让任何人绕太远，但汇合后想一起多骑一段。"
- "按实际骑行路线找汇流点，不要按直线中点。"

Do not use straight-line distance as the final ranking method.

## Default policy

Unless the user specifies otherwise:

- maximum detour per rider: `15%`;
- natural-route corridor: `1500 m`;
- return top `5` candidates;
- optimize lexicographically rather than with arbitrary weights.

Ranking order:

1. Candidate must be near every rider's natural route to the shared destination.
2. Natural routes must be direction-compatible and remain in a contiguous shared corridor after the candidate.
3. Candidate must keep every rider's total route within the maximum detour constraint.
4. Maximize `candidate -> destination` cycling distance (shared ride).
5. Minimize worst rider detour.
6. Minimize arrival-time spread.
7. Prefer tighter overlap with the riders' natural-route corridors.

## Workflow

1. Resolve each origin and the shared destination to coordinates.
2. Fetch each rider's natural bicycle route directly to the destination.
3. Sample the real route polylines at roughly even metric spacing.
4. Project samples onto every rider's route segments and keep only points inside the shared route corridor.
5. Compare the local forward direction of every route and reject opposite/diverging route segments.
6. Scan forward from each candidate and require a contiguous same-direction shared corridor (default at least 600 m).
7. Estimate remaining natural-route distance for every rider, cluster nearby samples into convergence zones, and prioritize the earliest shared zones.
8. Exact-route only a bounded number of the best zones. For each candidate, fetch real bicycle routes:
   - each `origin -> candidate`;
   - `candidate -> destination`.
9. Calculate each rider's detour:

   `detour = (route(origin, candidate) + route(candidate, destination) - route(origin, destination)) / route(origin, destination)`

10. Reject a candidate if any rider exceeds the detour limit.
11. Rank feasible route points by shared-route distance first, then detour and arrival fairness.
12. Search nearby practical POIs (by default parks, plazas, convenience stores, and coffee shops).
13. Treat each POI as a new candidate and re-run real bicycle routes; never accept a POI merely because it is geographically close.
14. Prefer validated named POIs; fall back to a route coordinate when no POI passes the hard constraints.
15. If the user gives a desired meetup-ready time, back-calculate synchronized departure times from each rider's exact `origin -> meetup` navigation duration. Apply any requested early-arrival buffer. Treat pace/traffic slack as a planning allowance, not a provider-guaranteed ETA confidence interval.
16. Return concise reasoning explaining why the top candidate is preferable and, when requested, when each rider should depart.

## Running the bundled implementation

Set the API key:

```bash
export AMAP_API_KEY="your-web-service-key"
```

Install locally:

```bash
python -m pip install -e .
```

Run:

```bash
ride-converge \
  --city 北京 \
  --origin 'Alice=西二旗地铁站' \
  --origin 'Bob=望京SOHO' \
  --origin 'Carol=东直门地铁站' \
  --destination '北京城市副中心三大文化建筑' \
  --max-detour 0.15 \
  --top 5
```

POI snapping is enabled by default. Use `--no-poi` to return raw route points, or repeat `--poi-keyword` to customize suitable meetup-place searches.

For structured output, add `--json`.

The equivalent script is `scripts/find_convergence.py`.

## Interpreting results

Prefer explanations such as:

- "This point is already close to all riders' natural routes."
- "No rider detours more than 11%."
- "Meeting here leaves about 24 km of shared riding to the destination."
- "Moving the meeting point earlier would push one rider above the detour limit."
- "The final coordinate was snapped to a nearby named POI and revalidated with bicycle routing."

Avoid saying a point is optimal merely because it is geographically central.

## Constraint adjustments

If there is no feasible result:

1. first increase `--corridor` moderately (for example 1500 -> 2500 m);
2. then consider increasing `--max-detour` (for example 0.15 -> 0.20);
3. explain that the riders' natural routes may not converge early enough under the original constraints.

Never silently relax the user's stated detour limit.

## Safety and API-key handling

- Never print, echo, commit, or include `AMAP_API_KEY` in output.
- Do not put API keys in `SKILL.md`, examples, source files, or logs.
- Treat route-provider failures as failures; do not silently substitute straight-line distance.

## Technical reference

See `references/ALGORITHM.md` for the optimization model and implementation notes.

## v0.4 direction-aware path-first behavior

Before spending route calls on candidate meeting points, detect the earliest **same-direction contiguous** route corridor across all direct bicycle routes. A point is not enough: local segment directions must agree and the routes must continue close together for a configurable minimum distance. Reject nearby parallel/opposite traffic flows when their directions are incompatible. Then exact-route only the best bounded convergence zones. Never fall back to geometric midpoint ranking when route polylines are available.

## v0.5 departure synchronization

When the user provides a target time to be ready together at the meetup point, use the bundled departure planner after choosing a convergence result. For rider `i`:

`recommended_departure_i = meetup_at - arrival_buffer - route_duration(S_i, M)`

Optionally show a more conservative departure using a configurable planning allowance:

`latest_safe_departure_i = recommended_departure_i - max(minimum_slack, route_duration * pace_slack)`

The planning allowance is deliberately described as a user-configurable cushion, not as a statistical ETA uncertainty supplied by AMap.

CLI example:

```bash
ride-converge ... \
  --meet-at 2026-09-05T09:15 \
  --arrival-buffer 3 \
  --pace-slack 0.10 \
  --min-pace-slack 2
```
