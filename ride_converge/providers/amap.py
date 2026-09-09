from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ..models import Place, Point, Route


def _read_dotenv_value(path: Path, name: str) -> str | None:
    """从 dotenv 文件读取单个配置值，不输出文件内容。"""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return None

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        key, separator, value = stripped.partition("=")
        if not separator or key.strip() != name:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        return value or None
    return None


def _dotenv_api_key() -> str | None:
    """依次在当前目录和项目根目录中查找 AMAP_API_KEY。"""
    candidates = [Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"]
    checked: set[Path] = set()
    for path in candidates:
        path = path.resolve()
        if path in checked:
            continue
        checked.add(path)
        value = _read_dotenv_value(path, "AMAP_API_KEY")
        if value:
            return value
    return None


class AMapError(RuntimeError):
    pass


class AMapProvider:
    GEO_URL = "https://restapi.amap.com/v3/geocode/geo"
    REGEO_URL = "https://restapi.amap.com/v3/geocode/regeo"
    BICYCLE_URL = "https://restapi.amap.com/v5/direction/bicycling"
    PLACE_AROUND_URL = "https://restapi.amap.com/v5/place/around"
    PLACE_TEXT_URL = "https://restapi.amap.com/v5/place/text"

    def __init__(self, api_key: str | None = None, timeout_s: float = 15.0):
        self.api_key = api_key or os.getenv("AMAP_API_KEY") or _dotenv_api_key()
        if not self.api_key:
            raise ValueError("必须设置 AMAP_API_KEY，或在项目根目录的 .env 文件中配置该值")
        self.timeout_s = timeout_s
        self._route_cache: dict[tuple[Point, Point], Route] = {}
        self._geocode_cache: dict[tuple[str, str | None], Point] = {}
        self._place_cache: dict[tuple[Point, int, str | None, int], list[Place]] = {}

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        query = urllib.parse.urlencode({**params, "key": self.api_key})
        req = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": "ride-converge/0.3"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                data = json.load(resp)
        except Exception:
            # 网络异常可能携带含 Key 的完整请求地址，不向客户端或日志透出。
            raise AMapError("高德地图请求失败，请检查网络连接或服务状态") from None

        status = str(data.get("status", ""))
        if status and status != "1":
            raise AMapError(f"高德地图返回错误：{data.get('info')}（{data.get('infocode')}）")
        if data.get("errmsg") and str(data.get("errcode", "0")) not in {"0", ""}:
            raise AMapError(f"高德地图返回错误：{data.get('errmsg')}（{data.get('errcode')}）")
        return data

    def geocode(self, address: str, city: str | None = None) -> Point:
        key = (address, city)
        if key in self._geocode_cache:
            return self._geocode_cache[key]
        params: dict[str, Any] = {"address": address}
        if city:
            params["city"] = city
        data = self._get(self.GEO_URL, params)
        geocodes = data.get("geocodes") or []
        if not geocodes:
            raise AMapError(f"无法解析地址：{address}")
        lng, lat = map(float, geocodes[0]["location"].split(","))
        point = Point(lng, lat)
        self._geocode_cache[key] = point
        return point

    def search_places(self, query: str, city: str, limit: int = 20) -> list[Place]:
        """返回供用户选择的地点列表，不自动采用第一条结果。"""
        data = self._get(self.PLACE_TEXT_URL, {
            "keywords": query, "region": city, "city_limit": "true",
            "page_size": min(25, max(1, int(limit))), "page_num": 1,
        })
        places: list[Place] = []
        seen: set[tuple[str, Point]] = set()
        pois = data.get("pois") or []
        if isinstance(pois, dict):
            pois = [pois]
        for poi in pois:
            if not isinstance(poi, dict):
                continue
            try:
                lng, lat = map(float, str(poi.get("location") or "").split(","))
                if not (-180 <= lng <= 180 and -90 <= lat <= 90):
                    continue
            except (ValueError, TypeError):
                continue
            name = str(poi.get("name") or "未命名地点")
            point = Point(lng, lat)
            if (name, point) in seen:
                continue
            seen.add((name, point))
            address_parts: list[str] = []
            for field in ("pname", "cityname", "adname", "address"):
                value = poi.get(field)
                if isinstance(value, str) and value and (not address_parts or address_parts[-1] != value):
                    address_parts.append(value)
            address = "".join(address_parts)
            places.append(Place(name=name, point=point, address=address or city,
                                category=poi.get("type") or None, provider_id=poi.get("id") or None))
        return places

    def reverse_geocode(self, point: Point) -> str | None:
        data = self._get(self.REGEO_URL, {"location": point.amap(), "radius": 500, "extensions": "base"})
        regeocode = data.get("regeocode") or {}
        return regeocode.get("formatted_address") or None

    def nearby_places(
        self,
        point: Point,
        *,
        radius_m: int = 500,
        keyword: str | None = None,
        limit: int = 10,
    ) -> list[Place]:
        radius_m = max(1, min(int(radius_m), 50_000))
        limit = max(1, min(int(limit), 25))
        cache_key = (point, radius_m, keyword, limit)
        if cache_key in self._place_cache:
            return list(self._place_cache[cache_key])

        params: dict[str, Any] = {
            "location": point.amap(),
            "radius": radius_m,
            "sortrule": "distance",
            "page_size": limit,
            "page_num": 1,
            "show_fields": "business",
        }
        if keyword:
            params["keywords"] = keyword
        data = self._get(self.PLACE_AROUND_URL, params)
        pois = data.get("pois") or []
        if isinstance(pois, dict):
            pois = [pois]

        out: list[Place] = []
        for poi in pois:
            loc = poi.get("location")
            if not loc or "," not in str(loc):
                continue
            lng, lat = map(float, str(loc).split(",", 1))
            business = poi.get("business") or {}
            address = poi.get("address") or business.get("address") or None
            category = poi.get("type") or business.get("tag") or None
            out.append(
                Place(
                    name=str(poi.get("name") or "未命名地点"),
                    point=Point(lng, lat),
                    address=str(address) if address else None,
                    category=str(category) if category else None,
                    provider_id=str(poi.get("id")) if poi.get("id") else None,
                )
            )
        self._place_cache[cache_key] = out
        return list(out)

    def bicycle_route(self, origin: Point, destination: Point) -> Route:
        cache_key = (origin, destination)
        if cache_key in self._route_cache:
            return self._route_cache[cache_key]

        data = self._get(
            self.BICYCLE_URL,
            {
                "origin": origin.amap(),
                "destination": destination.amap(),
                "show_fields": "cost,navi,polyline",
                "alternative_route": 1,
                "output": "JSON",
            },
        )
        route = data.get("route") or data.get("data") or {}
        paths = route.get("paths") or []
        if isinstance(paths, dict):
            paths = [paths]
        if not paths:
            raise AMapError(f"没有可用的骑行路线：{origin.amap()} -> {destination.amap()}")
        path = paths[0]
        distance = float(path.get("distance") or 0)
        duration = float(path.get("duration") or (path.get("cost") or {}).get("duration") or 0)
        points: list[Point] = []
        steps = path.get("steps") or []
        if isinstance(steps, dict):
            steps = [steps]
        for step in steps:
            poly = step.get("polyline")
            if not poly:
                poly = ((step.get("navi") or {}).get("polyline"))
            if not poly:
                poly = (((step.get("cost") or {}).get("navi") or {}).get("polyline"))
            if not poly:
                continue
            for token in str(poly).split(";"):
                if not token or "," not in token:
                    continue
                lng, lat = token.split(",", 1)
                p = Point(float(lng), float(lat))
                if not points or p != points[-1]:
                    points.append(p)
        if not points:
            raise AMapError("高德地图路线结果未返回路线折线；请检查 API 响应以及 show_fields 支持情况")
        result = Route(distance_m=distance, duration_s=duration, polyline=points)
        self._route_cache[cache_key] = result
        return result
