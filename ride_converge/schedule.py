from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import ConvergenceResult


@dataclass(frozen=True)
class RiderDeparture:
    name: str
    ride_duration_s: float
    recommended_departure_at: datetime
    expected_arrival_at: datetime
    buffer_s: float
    uncertainty_s: float
    latest_safe_departure_at: datetime


@dataclass(frozen=True)
class DeparturePlan:
    meetup_at: datetime
    riders: list[RiderDeparture]
    buffer_s: float
    uncertainty_ratio: float
    minimum_uncertainty_s: float

    @property
    def earliest_departure_at(self) -> datetime:
        return min(r.recommended_departure_at for r in self.riders)

    @property
    def latest_departure_at(self) -> datetime:
        return max(r.recommended_departure_at for r in self.riders)

    @property
    def departure_spread_s(self) -> float:
        return (self.latest_departure_at - self.earliest_departure_at).total_seconds()


def plan_departures(
    result: ConvergenceResult,
    meetup_at: datetime,
    *,
    buffer_s: float = 180.0,
    uncertainty_ratio: float = 0.10,
    minimum_uncertainty_s: float = 120.0,
) -> DeparturePlan:
    """Back-calculate synchronized departure times for one convergence result.

    ``meetup_at`` is the planned time the group wants to be ready at the meetup point.
    ``buffer_s`` makes each rider's expected arrival earlier than that time.

    Navigation durations are estimates, not confidence intervals. ``uncertainty_ratio`` and
    ``minimum_uncertainty_s`` are therefore only a configurable planning allowance used to
    show a conservative latest-safe departure time; they are not a provider-guaranteed ETA.
    """
    if buffer_s < 0:
        raise ValueError("buffer_s must be >= 0")
    if uncertainty_ratio < 0:
        raise ValueError("uncertainty_ratio must be >= 0")
    if minimum_uncertainty_s < 0:
        raise ValueError("minimum_uncertainty_s must be >= 0")
    if not result.riders:
        raise ValueError("Convergence result must include at least one rider")

    expected_arrival = meetup_at - timedelta(seconds=buffer_s)
    schedules: list[RiderDeparture] = []
    for rider in result.riders:
        ride_s = max(0.0, rider.to_meet_duration_s)
        uncertainty_s = max(minimum_uncertainty_s, ride_s * uncertainty_ratio)
        recommended = expected_arrival - timedelta(seconds=ride_s)
        latest_safe = recommended - timedelta(seconds=uncertainty_s)
        schedules.append(
            RiderDeparture(
                name=rider.name,
                ride_duration_s=ride_s,
                recommended_departure_at=recommended,
                expected_arrival_at=expected_arrival,
                buffer_s=buffer_s,
                uncertainty_s=uncertainty_s,
                latest_safe_departure_at=latest_safe,
            )
        )

    return DeparturePlan(
        meetup_at=meetup_at,
        riders=schedules,
        buffer_s=buffer_s,
        uncertainty_ratio=uncertainty_ratio,
        minimum_uncertainty_s=minimum_uncertainty_s,
    )
