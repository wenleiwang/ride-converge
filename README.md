# ride-converge

**面向骑行者的路径优先会合规划：让多名骑行者前往同一个目的地。**

`ride-converge` 不会简单寻找地理中点，而是沿骑行者的实际骑行路线寻找较早且实用的会合点，在限制每个人绕行距离的同时，尽可能增加会合后共同骑行的路程。

```text
A ---------\\
            \\
B -----------● M ===================> D
            /
C ----------/

             <---- 共同骑行 ---->
```

默认优化目标为：

> 在满足路线兼容性和每位骑行者绕行上限的前提下，最大化共同骑行距离。

## 与寻找中点有何不同

几何中点不会考虑河流、环路、自行车通行限制，以及每位骑行者实际路线的形状。本项目以每位骑行者前往最终目的地的真实骑行路线为基础，在这些路径周围搜索会合候选点。

## 亮点

- 为选定的会合结果新增**出发时间同步**功能。
- 支持设置团队希望在会合点准备就绪的本地目标时间。
- 根据每位骑行者准确的 `起点 -> 会合点` 路线耗时，反推出发时间。
- 支持提前到达缓冲时间，以及单独配置的行程规划余量。
- 同时提供常规建议出发时间和更保守的 `latest_safe_departure_at`。
- 保留 v0.4 中方向感知、连续共同行驶走廊检测和兴趣点重新验证功能。

## 功能特性

- 通过高德地图 Web 服务 API 获取真实骑行路线。
- 支持多名骑行者前往同一个目的地。
- 根据导航路线折线，以路径优先且感知方向的方式生成候选点。
- 为每位骑行者设置严格的最大绕行限制。
- 最大化从 `会合点 -> 目的地` 的共同骑行路程。
- 使用到达时间公平性作为排序时的决胜条件。
- 可根据目标会合就绪时间规划同步出发时间。
- 将候选点吸附到实用的兴趣点，并重新进行完整路线验证。
- 提供与 Agent Skills 兼容的 `SKILL.md`。
- 提供命令行界面和 Python API。
- Python 运行时不依赖第三方软件包。

## 使用要求

- Python 3.10 或更高版本
- 高德地图 Web 服务 API 密钥
- 实时路线规划所需的互联网连接

推荐复制示例文件，并在项目根目录的 `.env` 中填写密钥：

```text
AMAP_API_KEY=你的高德Web服务密钥
```

程序会自动、静默地读取当前目录或项目根目录下的 `.env`。也可以使用系统环境变量；PowerShell 和 Bash 的写法分别如下：

```powershell
$env:AMAP_API_KEY = "你的高德Web服务密钥"
```

```bash
export AMAP_API_KEY="你的高德Web服务密钥"
```

`.env` 已被 Git 忽略。请勿打印、公开或提交真实密钥。

## 安装

```bash
git clone <你的仓库地址>
cd ride-converge
python -m pip install -e .
```

## 命令行示例

```bash
ride-converge \
  --city 北京 \
  --origin 'A=西单地铁站' \
  --origin 'B=丰台科技园' \
  --origin 'C=北京工业大学' \
  --destination '潭柘寺' \
  --max-detour 0.15 \
  --corridor 1500 \
  --top 5
```

自定义会合点兴趣点：

```bash
ride-converge ... \
  --poi-radius 700 \
  --poi-keyword 公园 \
  --poi-keyword 广场 \
  --poi-keyword 便利店
```

禁用兴趣点吸附：

```bash
ride-converge ... --no-poi
```

输出结构化数据：

```bash
ride-converge ... --json
```

## Web 页面

项目提供本地 Web 规划页面，支持动态添加骑行者和途经点、上下调整途经点顺序、地址搜索、地图点击选点、调整约束，并在地图中回显起点、最近可行会合点、个人路线和共同骑行路线。途经点按 `M -> W1 -> W2 -> … -> D` 的顺序连接，用于控制会合后团队一起移动的路线。

在项目根目录运行：

```bash
python -m ride_converge.web.server
```

然后访问：

```text
http://127.0.0.1:8765
```

重新执行 `python -m pip install -e .` 后，也可以使用：

```bash
ride-converge-web
```

页面通过本机 Python 服务访问高德地图，`AMAP_API_KEY` 不会发送到浏览器。底图使用 Leaflet 和 OpenStreetMap；高德的 GCJ-02 坐标会在后端转换后再用于底图显示。

## 微信小程序

仓库包含可直接导入微信开发者工具的原生小程序，AppID 为 `wx35c145cb4a63ae54`。支持动态添加骑行者起点、多个有序途经点、最终目的地、地点搜索、地图选点、真实路线规划和多方案地图回显。

```text
项目根目录
├── project.config.json        微信开发者工具项目配置
├── miniprogram/               小程序源码
├── deploy/nginx/              HTTPS 反向代理模板
└── deploy/systemd/            Python 后端服务模板
```

生产接口地址已配置为：

```text
https://ride-converge.wenlei.wang
```

小程序不包含高德 Key。地点搜索、逆地理编码和骑行路线均通过上述 HTTPS 域名请求 Python 后端，再由后端读取 `.env` 并调用高德 Web 服务。完整的服务器部署、Nginx 配置、微信合法域名设置、真机测试和提审步骤见 [`references/WECHAT_MINIPROGRAM.md`](references/WECHAT_MINIPROGRAM.md)。

> 域名使用连字符 `ride-converge`，不要使用下划线形式 `ride_converge`。

### 出发时间同步

如果团队希望在指定的本地时间一起准备就绪：

```bash
ride-converge \
  --city 北京 \
  --origin 'A=西单地铁站' \
  --origin 'B=丰台科技园' \
  --destination '潭柘寺' \
  --meet-at 2026-09-05T09:15 \
  --arrival-buffer 3 \
  --pace-slack 0.10 \
  --min-pace-slack 2
```

`--meet-at` 表示团队希望在会合点准备就绪的时间。本例使用默认的 3 分钟提前到达缓冲，因此会为每位骑行者规划在 09:12 到达。`--pace-slack` 和 `--min-pace-slack` 会额外生成一个更保守的出发时间建议；这是一项规划缓冲，**并非**路线服务商保证的预计到达时间置信区间。

示例解读：

```text
A：08:42 出发（更稳妥的建议：08:39，包含 3 分钟规划余量）
B：08:52 出发（更稳妥的建议：08:50，包含 2 分钟规划余量）
共同准备就绪时间：09:15
```

## Python 编程接口

```python
from ride_converge import Options, Rider, find_convergence
from ride_converge.providers import AMapProvider

provider = AMapProvider()
riders = [
    Rider("A", provider.geocode("西单地铁站", "北京")),
    Rider("B", provider.geocode("丰台科技园", "北京")),
]
destination = provider.geocode("潭柘寺", "北京")

results = find_convergence(
    provider,
    riders,
    destination,
    Options(max_detour_ratio=0.15, snap_to_poi=True, top_n=5),
)

print(results[0].label, results[0].shared_distance_m)

from datetime import datetime
from ride_converge import plan_departures

plan = plan_departures(
    results[0],
    datetime.fromisoformat("2026-09-05T09:15"),
    buffer_s=180,
)
for rider in plan.riders:
    print(rider.name, rider.recommended_departure_at)
```

## 优化模型

对于骑行者 `i`：

```text
direct_i = route(S_i -> D)
via_i    = route(S_i -> M) + route(M -> D)
detour_i = (via_i - direct_i) / direct_i
```

出现以下情况时，候选点会被淘汰：

```text
max(detour_i) > 配置的绕行上限
```

在路线兼容且满足约束的候选点中，排序会依次优先考虑：

1. 最大化共同骑行距离 `M -> D`；
2. 最小化绕行比例最高者的绕行比例；
3. 最小化骑行者到达时间的差距；
4. 更接近所有人的自然路线；
5. 若其他条件相同，优先选择同向性和连续走廊依据更充分的候选点。

兴趣点吸附是第二阶段处理。附近有名称的地点会被视为新的候选点，并且必须通过相同的路线走廊和绕行约束验证。

详细信息请参阅 [`references/ALGORITHM.md`](references/ALGORITHM.md)。

## API 使用说明

对于 `N` 名骑行者，评估一个原始候选点大约需要查询 `N + 1` 次路线。兴趣点吸附还会增加一次有数量上限的候选点处理。v0.3 已使用进程内缓存并对候选点数量设置保守上限，但托管服务仍应加入持久化缓存、配额和单次请求预算。

## 测试

测试使用确定性的模拟路由器和模拟兴趣点搜索，不需要 API 密钥：

```bash
python -m unittest discover -s tests -v
```

## 路线图

- [x] 将会合点坐标吸附到附近实用的兴趣点。
- [x] 使用基于线段投影的走廊距离，支持城市和区域级路线规划。
- [ ] 持久化路线响应缓存。
- [ ] 在路线服务商提供相关数据时，支持可选的道路路段或自行车道身份检查。
- [ ] 支持更多路线服务商。
- [x] 出发时间同步。
- [ ] 可选的网页界面或地图可视化。

## 许可证

本项目采用 MIT 许可证。请参阅 [`LICENSE`](LICENSE)；中文参考译文见 [`LICENSE.zh-CN.md`](LICENSE.zh-CN.md)。

## 走廊控制参数

```bash
ride-converge ... \
  --sample-spacing 600 \
  --zone-radius 700 \
  --validation-candidates 18 \
  --min-direction-cosine 0.65 \
  --min-shared-segment 600
```

- `--sample-spacing`：检测走廊前，对自然路线进行采样的密度。
- `--zone-radius`：将距离较近的共同走廊采样点合并为一个会合区域。
- `--validation-candidates`：限制接受高成本精确骑行路线验证的原始区域数量。
- `--min-direction-cosine`：淘汰局部前进方向差异过大的路线。`1` 表示方向完全相同，`0` 表示垂直，`-1` 表示相反。
- `--min-shared-segment`：要求经过候选点后，自然路线仍保持空间邻近且方向兼容至少指定米数。

使用 `--json` 可查看 `natural_shared_floor_m`、`route_remaining_spread_m`、`route_corridor_m`、`direction_alignment` 和 `contiguous_shared_m`。
