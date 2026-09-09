from __future__ import annotations

import json
import math
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ..cli import ChineseArgumentParser
from ..core import NoFeasibleConvergence, Options, find_convergence
from ..models import Point, Rider, Route
from ..providers.amap import AMapError, AMapProvider


STATIC_DIR = Path(__file__).resolve().parent
_PI = math.pi
_A = 6378245.0
_EE = 0.006693421622965943


def _out_of_china(lng: float, lat: float) -> bool:
    return not (72.004 <= lng <= 137.8347 and 0.8293 <= lat <= 55.8271)


def _transform_lat(lng: float, lat: float) -> float:
    value = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat
    value += 0.2 * math.sqrt(abs(lng))
    value += (20.0 * math.sin(6.0 * lng * _PI) + 20.0 * math.sin(2.0 * lng * _PI)) * 2.0 / 3.0
    value += (20.0 * math.sin(lat * _PI) + 40.0 * math.sin(lat / 3.0 * _PI)) * 2.0 / 3.0
    value += (160.0 * math.sin(lat / 12.0 * _PI) + 320.0 * math.sin(lat * _PI / 30.0)) * 2.0 / 3.0
    return value


def _transform_lng(lng: float, lat: float) -> float:
    value = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat
    value += 0.1 * math.sqrt(abs(lng))
    value += (20.0 * math.sin(6.0 * lng * _PI) + 20.0 * math.sin(2.0 * lng * _PI)) * 2.0 / 3.0
    value += (20.0 * math.sin(lng * _PI) + 40.0 * math.sin(lng / 3.0 * _PI)) * 2.0 / 3.0
    value += (150.0 * math.sin(lng / 12.0 * _PI) + 300.0 * math.sin(lng / 30.0 * _PI)) * 2.0 / 3.0
    return value


def _delta(lng: float, lat: float) -> tuple[float, float]:
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * _PI
    magic = 1 - _EE * math.sin(radlat) ** 2
    sqrt_magic = math.sqrt(magic)
    dlat = dlat * 180.0 / ((_A * (1 - _EE)) / (magic * sqrt_magic) * _PI)
    dlng = dlng * 180.0 / (_A / sqrt_magic * math.cos(radlat) * _PI)
    return dlng, dlat


def gcj02_to_wgs84(point: Point) -> Point:
    """将高德使用的 GCJ-02 坐标转换为底图使用的 WGS84 坐标。"""
    if _out_of_china(point.lng, point.lat):
        return point
    dlng, dlat = _delta(point.lng, point.lat)
    return Point(point.lng - dlng, point.lat - dlat)


def wgs84_to_gcj02(point: Point) -> Point:
    """将地图点击得到的 WGS84 坐标转换为高德使用的 GCJ-02 坐标。"""
    if _out_of_china(point.lng, point.lat):
        return point
    dlng, dlat = _delta(point.lng, point.lat)
    return Point(point.lng + dlng, point.lat + dlat)


def _point_payload(point: Point) -> dict[str, Any]:
    wgs = gcj02_to_wgs84(point)
    return {
        "gcj": {"lng": point.lng, "lat": point.lat},
        "wgs": {"lng": wgs.lng, "lat": wgs.lat},
    }


def _polyline_payload(points: list[Point]) -> list[list[float]]:
    return [[p.lat, p.lng] for p in (gcj02_to_wgs84(point) for point in points)]


def _polyline_gcj_payload(points: list[Point]) -> list[list[float]]:
    """返回高德与微信地图组件可直接使用的 GCJ-02 坐标。"""
    return [[point.lat, point.lng] for point in points]


def _join_route_polylines(routes: list[Any]) -> list[Point]:
    """按顺序拼接多段路线，并去掉相邻重复点。"""
    points: list[Point] = []
    for route in routes:
        for point in route.polyline:
            if not points or point != points[-1]:
                points.append(point)
    return points


def _required_text(value: Any, label: str, maximum: int = 160) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label}不能为空")
    if len(text) > maximum:
        raise ValueError(f"{label}过长")
    return text


def _payload_point(value: Any, label: str) -> Point:
    try:
        gcj = value["gcj"]
        point = Point(float(gcj["lng"]), float(gcj["lat"]))
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"{label}缺少有效坐标") from None
    if not (-180 <= point.lng <= 180 and -90 <= point.lat <= 90):
        raise ValueError(f"{label}坐标超出范围")
    return point


def _fallback_plan_result(provider: AMapProvider, riders: list[Rider], targets: list[dict[str, Any]]) -> dict[str, Any]:
    """在首个共同必经点集合。只使用实际路线，不伪装成通过约束的推荐。"""
    points = [_payload_point(item["point"], "共同路线地点") for item in targets]
    meeting = points[0]

    def route(start: Point, end: Point) -> Route:
        # 起点就在集合处或相邻途经点相同，无须向高德请求零长度路线。
        if start == end:
            return Route(0, 0, [start])
        result = provider.bicycle_route(start, end)
        if not result.polyline:
            raise AMapError("保底路线未返回有效折线，请调整地点后重试")
        return result

    rider_routes = [route(rider.origin, meeting) for rider in riders]
    shared_legs = [route(start, end) for start, end in zip(points, points[1:])]
    shared_points = _join_route_polylines(shared_legs)
    shared_distance = sum(leg.distance_m for leg in shared_legs)
    shared_duration = sum(leg.duration_s for leg in shared_legs)
    distances = [item.distance_m for item in rider_routes]
    durations = [item.duration_s for item in rider_routes]
    common_route = " → ".join(item["address"] for item in targets)
    has_shared_route = any(start != end for start, end in zip(points, points[1:]))
    instruction = (
        f"分别前往「{targets[0]['address']}」汇合，再按「{common_route}」一起骑行。"
        if has_shared_route else
        f"分别前往「{targets[0]['address']}」集合；此处已是最终目的地，没有后续共同路段。"
    )
    return {
        "label": targets[0]["address"], "address": targets[0]["address"],
        "category": "集合点", "is_poi": False, "point": _point_payload(meeting),
        "is_fallback": True, "fallback_reason": "未找到满足路线方向、连续走廊和绕行限制的汇合方案。",
        "fallback_instruction": instruction, "has_shared_route": has_shared_route,
        "constraints_satisfied": False, "shared_targets": targets[1:],
        "shared_distance_m": shared_distance, "shared_duration_s": shared_duration,
        "max_to_meet_distance_m": max(distances), "avg_to_meet_distance_m": sum(distances) / len(distances),
        # 保底不宣称通过原汇合约束，也不显示未经评估的绕行比例。
        "max_detour_ratio": None, "direction_alignment": None, "contiguous_shared_m": None,
        "arrival_spread_s": max(durations) - min(durations),
        "riders": [
            {"name": rider.name, "to_meet_distance_m": leg.distance_m, "to_meet_duration_s": leg.duration_s,
             "total_via_distance_m": leg.distance_m + shared_distance, "direct_distance_m": None, "detour_ratio": None}
            for rider, leg in zip(riders, rider_routes)
        ],
        "routes": {
            "riders": [_polyline_payload(item.polyline) for item in rider_routes],
            "shared": _polyline_payload(shared_points),
            "riders_gcj": [_polyline_gcj_payload(item.polyline) for item in rider_routes],
            "shared_gcj": _polyline_gcj_payload(shared_points),
        },
    }


class RideWebServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int]):
        super().__init__(address, RideWebHandler)
        self.provider = AMapProvider()


class RideWebHandler(SimpleHTTPRequestHandler):
    server: RideWebServer

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:
        path = self.path
        if path == "/api/health":
            self._json({"status": "ok", "service": "ride-converge"})
            return
        if path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        if path not in {"/", "/index.html", "/app.css", "/app.js"}:
            body = "文件不存在".encode("utf-8")
            self.send_response(HTTPStatus.NOT_FOUND)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.path = "/index.html" if path == "/" else path
        super().do_GET()

    def do_POST(self) -> None:
        try:
            payload = self._read_json()
            if self.path == "/api/search":
                result = self._search(payload)
            elif self.path == "/api/search/places":
                result = self._search_places(payload)
            elif self.path == "/api/reverse":
                result = self._reverse(payload)
            elif self.path == "/api/plan":
                result = self._plan(payload)
            else:
                self._json({"error": "接口不存在"}, HTTPStatus.NOT_FOUND)
                return
            self._json(result)
        except (ValueError, AMapError, NoFeasibleConvergence) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception:
            self._json({"error": "服务器处理请求时发生错误"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("请求长度无效") from None
        if not (0 < length <= 65_536):
            raise ValueError("请求内容为空或过大")
        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("请求不是有效的 JSON") from None
        if not isinstance(payload, dict):
            raise ValueError("请求内容必须是对象")
        return payload

    def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _search(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = _required_text(payload.get("query"), "搜索内容")
        city = _required_text(payload.get("city") or "北京", "城市", 40)
        point = self.server.provider.geocode(query, city)
        address = self.server.provider.reverse_geocode(point) or query
        return {"label": query, "address": address, "point": _point_payload(point)}

    def _search_places(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = _required_text(payload.get("query"), "搜索内容", 80)
        city = _required_text(payload.get("city") or "北京", "城市", 40)
        places = self.server.provider.search_places(query, city)
        return {"results": [
            {"id": item.provider_id or str(index), "label": item.name,
             "address": item.address, "category": item.category,
             "point": _point_payload(item.point)}
            for index, item in enumerate(places)
        ]}

    def _reverse(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            point = Point(float(payload["lng"]), float(payload["lat"]))
        except (KeyError, TypeError, ValueError):
            raise ValueError("地图坐标无效") from None
        # Web 页面的 Leaflet 地图传入 WGS84；微信地图组件传入 GCJ-02。
        gcj = point if payload.get("coordinate_system") == "gcj" else wgs84_to_gcj02(point)
        address = self.server.provider.reverse_geocode(gcj) or f"{gcj.lng:.6f},{gcj.lat:.6f}"
        return {"label": address, "address": address, "point": _point_payload(gcj)}

    def _plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        city = _required_text(payload.get("city") or "北京", "城市", 40)
        raw_origins = payload.get("origins")
        if not isinstance(raw_origins, list) or not (2 <= len(raw_origins) <= 8):
            raise ValueError("起点数量必须介于 2 和 8 之间")

        riders: list[Rider] = []
        origin_data: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_origins, 1):
            if not isinstance(raw, dict):
                raise ValueError(f"第 {index} 个起点无效")
            name = _required_text(raw.get("name") or f"骑行者{index}", f"第 {index} 个骑行者名称", 30)
            address = _required_text(raw.get("address"), f"{name} 的起点")
            point = _payload_point(raw.get("point"), f"{name} 的起点") if raw.get("point") else self.server.provider.geocode(address, city)
            riders.append(Rider(name, point))
            origin_data.append({"name": name, "address": address, "point": _point_payload(point)})

        raw_waypoints = payload.get("waypoints") or []
        if not isinstance(raw_waypoints, list) or len(raw_waypoints) > 8:
            raise ValueError("途经点数量必须介于 0 和 8 之间")
        waypoints: list[Point] = []
        waypoint_data: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_waypoints, 1):
            if not isinstance(raw, dict):
                raise ValueError(f"第 {index} 个途经点无效")
            address = _required_text(raw.get("address"), f"第 {index} 个途经点")
            point = (
                _payload_point(raw.get("point"), f"第 {index} 个途经点")
                if raw.get("point")
                else self.server.provider.geocode(address, city)
            )
            waypoints.append(point)
            waypoint_data.append({"address": address, "point": _point_payload(point)})

        raw_destination = payload.get("destination")
        if not isinstance(raw_destination, dict):
            raise ValueError("目的地无效")
        destination_address = _required_text(raw_destination.get("address"), "目的地")
        destination = (
            _payload_point(raw_destination.get("point"), "目的地")
            if raw_destination.get("point")
            else self.server.provider.geocode(destination_address, city)
        )

        chain_targets = [*waypoints, destination]
        convergence_anchor = chain_targets[0]
        raw_options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
        requested_top_n = min(5, max(1, int(raw_options.get("top_n", 3))))
        options = Options(
            max_detour_ratio=float(raw_options.get("max_detour_ratio", 0.15)),
            route_corridor_m=float(raw_options.get("route_corridor_m", 1500)),
            top_n=16,
            validation_candidates=18,
            min_direction_cosine=float(raw_options.get("min_direction_cosine", 0.65)),
            min_contiguous_shared_m=float(raw_options.get("min_contiguous_shared_m", 600)),
        )
        try:
            results = find_convergence(self.server.provider, riders, convergence_anchor, options)
        except NoFeasibleConvergence:
            results = []
        if not results:
            destination_data = {"address": destination_address, "point": _point_payload(destination)}
            fallback = _fallback_plan_result(self.server.provider, riders, [*waypoint_data, destination_data])
            return {
                "city": city, "origins": origin_data, "waypoints": waypoint_data,
                "destination": destination_data, "ranking": "fallback_first_common_stop",
                "is_fallback": True, "results": [fallback],
            }
        results.sort(
            key=lambda result: (
                max(item.to_meet_distance_m for item in result.riders),
                sum(item.to_meet_distance_m for item in result.riders) / len(result.riders),
                result.max_detour_ratio,
                result.arrival_spread_s,
            )
        )
        results = results[:requested_top_n]

        serialized_results: list[dict[str, Any]] = []
        for result in results:
            shared_legs = [self.server.provider.bicycle_route(result.point, convergence_anchor)]
            shared_legs.extend(
                self.server.provider.bicycle_route(origin, target)
                for origin, target in zip(chain_targets, chain_targets[1:])
            )
            shared_distance_m = sum(route.distance_m for route in shared_legs)
            shared_duration_s = sum(route.duration_s for route in shared_legs)
            rider_routes = [self.server.provider.bicycle_route(rider.origin, result.point) for rider in riders]
            max_to_meet_distance_m = max(item.to_meet_distance_m for item in result.riders)
            avg_to_meet_distance_m = sum(item.to_meet_distance_m for item in result.riders) / len(result.riders)
            serialized_results.append(
                {
                    "label": result.label or "路线会合点",
                    "address": result.address,
                    "category": result.category,
                    "is_poi": result.is_poi,
                    "is_fallback": False,
                    "point": _point_payload(result.point),
                    "shared_distance_m": shared_distance_m,
                    "shared_duration_s": shared_duration_s,
                    "max_to_meet_distance_m": max_to_meet_distance_m,
                    "avg_to_meet_distance_m": avg_to_meet_distance_m,
                    "max_detour_ratio": result.max_detour_ratio,
                    "arrival_spread_s": result.arrival_spread_s,
                    "direction_alignment": result.direction_alignment,
                    "contiguous_shared_m": result.contiguous_shared_m,
                    "riders": [item.__dict__ for item in result.riders],
                    "routes": {
                        "riders": [_polyline_payload(route.polyline) for route in rider_routes],
                        "shared": _polyline_payload(_join_route_polylines(shared_legs)),
                        "riders_gcj": [_polyline_gcj_payload(route.polyline) for route in rider_routes],
                        "shared_gcj": _polyline_gcj_payload(_join_route_polylines(shared_legs)),
                    },
                }
            )

        return {
            "city": city,
            "origins": origin_data,
            "waypoints": waypoint_data,
            "destination": {"address": destination_address, "point": _point_payload(destination)},
            "ranking": "nearest_fair",
            "is_fallback": False,
            "results": serialized_results,
        }


def main() -> None:
    parser = ChineseArgumentParser(prog="ride-converge-web", description="启动 ride-converge 本地 Web 页面", add_help=False)
    parser.add_argument("-h", "--help", action="help", help="显示此帮助信息并退出")
    parser.add_argument("--host", default="127.0.0.1", metavar="地址", help="监听地址（默认：127.0.0.1）")
    parser.add_argument("--port", type=int, default=8765, metavar="端口", help="监听端口（默认：8765）")
    args = parser.parse_args()
    server = RideWebServer((args.host, args.port))
    print(f"ride-converge Web 页面已启动：http://{args.host}:{args.port}")
    print("按 Ctrl+C 停止服务。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止服务……")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
