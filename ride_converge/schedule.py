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
    """根据一个会合结果反推同步出发时间。

    ``meetup_at`` 是团队计划在会合点准备就绪的时间。
    ``buffer_s`` 让每位骑行者的预计到达时间早于该时间。

    导航耗时是估算值，并非置信区间。因此，``uncertainty_ratio`` 和
    ``minimum_uncertainty_s`` 只是可配置的规划余量，用于给出更保守的稳妥出发时间；
    它们不是路线服务商保证的预计到达时间。
    """
    if buffer_s < 0:
        raise ValueError("buffer_s 必须大于或等于 0")
    if uncertainty_ratio < 0:
        raise ValueError("uncertainty_ratio 必须大于或等于 0")
    if minimum_uncertainty_s < 0:
        raise ValueError("minimum_uncertainty_s 必须大于或等于 0")
    if not result.riders:
        raise ValueError("会合结果必须至少包含一名骑行者")

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
