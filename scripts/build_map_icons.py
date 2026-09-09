"""生成微信原生地图使用的本地点位图标；无需第三方依赖。"""
from pathlib import Path
import struct
import zlib


def write_pin(path: Path, color: tuple[int, int, int]) -> None:
    width, height, sampling = 56, 72, 3
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            channels = [0, 0, 0, 0]
            for sy in range(sampling):
                for sx in range(sampling):
                    px, py = (x + (sx + 0.5) / sampling) / 2, (y + (sy + 0.5) / sampling) / 2
                    inside = (px - 14) ** 2 + (py - 12) ** 2 <= 11 ** 2
                    inside |= 16 <= py <= 35 and abs(px - 14) <= (35 - py) * 0.52
                    if inside:
                        fill = (255, 255, 255) if (px - 14) ** 2 + (py - 12) ** 2 < 4 ** 2 else color
                        for channel in range(3):
                            channels[channel] += fill[channel]
                        channels[3] += 255
            samples_inside = channels[3] / 255
            rgb = [round(channel / samples_inside) if samples_inside else 0 for channel in channels[:3]]
            rows.extend([*rgb, round(channels[3] / (sampling ** 2))])

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(rows))) + chunk(b"IEND", b"")
    path.write_bytes(png)


if __name__ == "__main__":
    directory = Path(__file__).resolve().parents[1] / "miniprogram" / "assets"
    directory.mkdir(exist_ok=True)
    for name, color in {"origin": (52, 120, 246), "waypoint": (245, 158, 11), "destination": (239, 83, 80), "meeting": (22, 165, 106)}.items():
        write_pin(directory / f"{name}.png", color)
    print("已生成 4 个本地地图标记图标")
