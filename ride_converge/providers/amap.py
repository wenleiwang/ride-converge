from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

from ..models import Place, Point, Route


class AMapError(RuntimeError):
    pass


class AMapProvider:
    GEO_URL = "https://restapi.amap.com/v3/geocode/geo"
    REGEO_URL = "https://restapi.amap.com/v3/geocode/regeo"
    BICYCLE_URL = "https://restapi.amap.com/v5/direction/bicycling"
    PLACE_AROUND_URL = "https://restapi.amap.com/v5/place/around"

    def __init__(self, api_key: str | None = None, timeout_s: float = 15.0):
        self.api_key = api_key or os.getenv("AMAP_API_KEY")
        if not self.api_key:
            raise ValueError("AMAP_API_KEY is required")
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
        except Exception as exc:
            raise AMapError(f"AMap request failed: {exc}") from exc

        status = str(data.get("status", ""))
        if status and status != "1":
            raise AMapError(f"AMap error: {data.get('info')} ({data.get('infocode')})")
        if data.get("errmsg") and str(data.get("errcode", "0")) not in {"0", ""}:
            raise AMapError(f"AMap error: {data.get('errmsg')} ({data.get('errcode')})")
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
            raise AMapError(f"Could not geocode: {address}")
        lng, lat = map(float, geocodes[0]["location"].split(","))
        point = Point(lng, lat)
        self._geocode_cache[key] = point
        return point

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
                    name=str(poi.get("name") or "unnamed place"),
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
            raise AMapError(f"No bicycle route: {origin.amap()} -> {destination.amap()}")
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
            raise AMapError("AMap route returned no polyline; check API response/show_fields support")
        result = Route(distance_m=distance, duration_s=duration, polyline=points)
        self._route_cache[cache_key] = result
        return result
