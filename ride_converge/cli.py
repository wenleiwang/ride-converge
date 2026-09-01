from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime

from .core import Options, find_convergence
from .models import Rider
from .providers.amap import AMapProvider
from .schedule import plan_departures


class ChineseArgumentParser(argparse.ArgumentParser):
    """为 argparse 的固定界面文字提供中文显示。"""

    def format_usage(self) -> str:
        return super().format_usage().replace("usage:", "用法：", 1)

    def format_help(self) -> str:
        return super().format_help().replace("usage:", "用法：", 1).replace("options:", "选项：", 1)

    def error(self, message: str) -> None:
        message = message.replace("the following arguments are required:", "缺少以下必需参数：")
        message = message.replace("unrecognized arguments:", "无法识别的参数：")
        message = message.replace("invalid float value:", "无效的小数：")
        message = message.replace("invalid int value:", "无效的整数：")
        message = message.replace("expected one argument", "需要提供一个值")
        message = re.sub(r"argument ([^:]+):", r"参数 \1：", message)
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}：错误：{message}\n")


def _km(m: float) -> str:
    return f"{m / 1000:.1f} 公里"


def _mins(s: float) -> str:
    return f"{s / 60:.0f} 分钟"


def main() -> None:
    parser = ChineseArgumentParser(prog="ride-converge", description="寻找路径优先的骑行会合点", add_help=False)
    parser.add_argument("-h", "--help", action="help", help="显示此帮助信息并退出")
    parser.add_argument("--city", default="北京", metavar="城市", help="用于地址解析的城市（默认：北京）")
    parser.add_argument("--origin", action="append", required=True, metavar="名称=地址", help='名称=地址；每名骑行者分别指定一次')
    parser.add_argument("--destination", required=True, metavar="目的地", help="共同目的地")
    parser.add_argument("--max-detour", type=float, default=0.15, metavar="比例", help="最大绕行比例，例如 0.15")
    parser.add_argument("--corridor", type=float, default=1500, metavar="米数", help="自然路线走廊宽度，单位为米")
    parser.add_argument("--top", type=int, default=5, metavar="数量", help="返回的候选结果数量（默认：5）")
    parser.add_argument("--sample-spacing", type=float, default=600, metavar="米数", help="路线折线采样间距，单位为米")
    parser.add_argument("--zone-radius", type=float, default=700, metavar="米数", help="将附近的共同走廊采样点合并为一个区域")
    parser.add_argument("--validation-candidates", type=int, default=18, metavar="数量", help="接受精确路线验证的原始会合区域数量上限")
    parser.add_argument(
        "--min-direction-cosine",
        type=float,
        default=0.65,
        metavar="一致度",
        help="自然路线前进方向的最小一致度（-1 到 1；0.65 约等于最大相差 49 度）",
    )
    parser.add_argument(
        "--min-shared-segment",
        type=float,
        default=600,
        metavar="米数",
        help="会合后同向且连续的自然路线走廊最短长度，单位为米",
    )
    parser.add_argument("--no-poi", action="store_true", help="返回路线坐标，不吸附到附近的兴趣点")
    parser.add_argument("--poi-radius", type=int, default=500, metavar="米数", help="在可行路线点周围搜索兴趣点的半径")
    parser.add_argument(
        "--poi-keyword",
        action="append",
        metavar="关键词",
        help="偏好的会合兴趣点关键词，可重复指定。默认：公园、广场、便利店、咖啡",
    )
    parser.add_argument(
        "--meet-at",
        metavar="日期时间",
        help="可选的本地 ISO 会合就绪时间，例如 2026-09-05T09:15；用于反推每人的出发时间",
    )
    parser.add_argument(
        "--arrival-buffer",
        type=float,
        default=3.0,
        metavar="分钟",
        help="骑行者应比 --meet-at 提前到达的分钟数（默认：3）",
    )
    parser.add_argument(
        "--pace-slack",
        type=float,
        default=0.10,
        metavar="比例",
        help="用于稳妥出发时间的规划余量，占路线预计耗时的比例（默认：0.10）",
    )
    parser.add_argument(
        "--min-pace-slack",
        type=float,
        default=2.0,
        metavar="分钟",
        help="稳妥出发时间采用的最小规划余量，单位为分钟（默认：2）",
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出结构化结果")
    args = parser.parse_args()

    provider = AMapProvider()
    riders: list[Rider] = []
    for raw in args.origin:
        if "=" not in raw:
            parser.error(f"起点 {raw!r} 格式无效，应使用‘名称=地址’格式")
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
            parser.error("--meet-at 必须是 ISO 格式的本地日期时间，例如 2026-09-05T09:15")
        if args.arrival_buffer < 0:
            parser.error("--arrival-buffer 必须大于或等于 0")
        if args.pace_slack < 0:
            parser.error("--pace-slack 必须大于或等于 0")
        if args.min_pace_slack < 0:
            parser.error("--min-pace-slack 必须大于或等于 0")

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
        poi = "兴趣点" if r.is_poi else "路线点"
        print(f"#{i} {r.label or r.point.amap()} [{poi}]")
        if r.address and r.address != r.label:
            print(f"  地址：{r.address}")
        print(f"  共同骑行：{_km(r.shared_distance_m)} / {_mins(r.shared_duration_s)}")
        print(f"  最大绕行：{r.max_detour_ratio:.1%}；到达时间差：{_mins(r.arrival_spread_s)}")
        if r.natural_shared_floor_m is not None:
            print(f"  自然路线走廊：剩余 {_km(r.natural_shared_floor_m)}；宽度 {r.route_corridor_m:.0f} 米")
        if r.direction_alignment is not None and r.contiguous_shared_m is not None:
            print(f"  方向一致度：{r.direction_alignment:.2f}；连续共同走廊：{_km(r.contiguous_shared_m)}")
        for rr in r.riders:
            print(f"  - {rr.name}：{_km(rr.to_meet_distance_m)}，{_mins(rr.to_meet_duration_s)}，绕行 {rr.detour_ratio:.1%}")
        if meetup_at is not None:
            plan = plan_departures(
                r,
                meetup_at,
                buffer_s=args.arrival_buffer * 60,
                uncertainty_ratio=args.pace_slack,
                minimum_uncertainty_s=args.min_pace_slack * 60,
            )
            print(f"  同步出发：在 {plan.meetup_at.isoformat(timespec='minutes')} 共同准备就绪")
            for departure in plan.riders:
                print(
                    f"    - {departure.name}：建议 {departure.recommended_departure_at.isoformat(timespec='minutes')} 出发；"
                    f"更稳妥的时间为 {departure.latest_safe_departure_at.isoformat(timespec='minutes')}，"
                    f"包含 {departure.uncertainty_s / 60:.0f} 分钟规划余量"
                )
