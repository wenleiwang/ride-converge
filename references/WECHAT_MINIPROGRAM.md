# 微信小程序发布说明

项目已经包含原生微信小程序，目录为 `miniprogram/`，项目配置为根目录的 `project.config.json`。小程序 AppID 已设置为 `wx35c145cb4a63ae54`。

## 架构与密钥安全

```text
微信小程序
    │ HTTPS：搜索、选点、生成方案
    ▼
ride-converge.wenlei.wang（Nginx）
    │ 反向代理
    ▼
127.0.0.1:8765（Python 服务）
    │ 使用服务器 .env 中的密钥
    ▼
高德 Web 服务 API
```

高德 Key 只放在服务器项目目录的 `.env` 中：

```text
AMAP_API_KEY=你的高德Web服务Key
```

不要把 Key 写进 `miniprogram/config.js`、提交到 Git，或配置成可由浏览器直接读取的变量。小程序使用高德提供的地点搜索、逆地理编码和骑行路线数据，地图绘制使用兼容 GCJ-02 坐标的微信原生地图组件。

**底图说明：** 当前小程序的交互底图是微信原生 `map` 组件，因此会显示腾讯地图等原生底图来源标识，并非高德底图。接入高德搜索接口或小程序 SDK 不会替换该底图，不能通过隐藏来源标识冒充高德地图。如果需要交互式高德底图，需要另行评估高德 JS API 网页与小程序 `web-view` 的接入条件；高德官方小程序插件另提供静态地图功能，但静态图不等同于可拖动、缩放的原生地图。参考[高德官方小程序地图说明](https://lbs.amap.com/api/wx/guide/create-map/static-map)。

## 一、部署 Python 服务

项目要求 Python 3.10 或更高版本。服务器系统自带的 Python 3.6 不要升级或替换，本项目使用 Miniconda 创建独立的 Python 3.11 环境。

### 1. 安装 Miniconda

先确认服务器架构：

```bash
uname -m
```

如果输出为 `x86_64`，下载安装 Miniconda：

```bash
cd /tmp
curl -O https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh
source ~/.bashrc
conda --version
```

安装时接受许可协议、使用默认安装目录，并在询问是否初始化 Conda 时选择 `yes`。如果服务器是 `aarch64`，应改用对应的 `Linux-aarch64` 安装包。

### 2. 创建 Conda 环境

```bash
conda create -n ride-converge python=3.11 pip -y
conda activate ride-converge
python --version
which python
```

如果首次创建环境时提示尚未接受 Anaconda 软件源服务条款，请先阅读并确认同意，然后执行：

```bash
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r
conda create -n ride-converge python=3.11 pip -y
```

当前服务器的 Conda Python 路径为：

```text
/root/miniconda3/envs/ride-converge/bin/python
```

### 3. 安装项目

将 `pyproject.toml`、`README.md` 和完整的 `ride_converge/` 目录复制到 `/opt/ride-converge`，然后执行：

```bash
cd /opt/ride-converge
conda activate ride-converge
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
```

不要从本机复制 `.venv`、Conda 环境、`__pycache__` 或 `*.egg-info`，它们应在服务器重新生成。

### 4. 配置高德 Key

在服务器创建仅限管理员读取的 `.env`：

```bash
cd /opt/ride-converge
touch .env
chmod 600 .env
```

写入以下内容，不要把真实 Key 提交到 Git 或写入小程序代码：

```text
AMAP_API_KEY=你的高德Web服务Key
```

### 5. 手动验证服务

```bash
/root/miniconda3/envs/ride-converge/bin/python -m ride_converge.web.server --host 127.0.0.1 --port 8765
```

另开一个终端检查：

```bash
curl http://127.0.0.1:8765/api/health
```

返回 `{"status":"ok","service":"ride-converge"}` 即表示服务正常。

### 6. 注册 systemd 服务

仓库提供的 `deploy/systemd/ride-converge.service` 已使用当前 Conda 解释器：

```ini
User=root
Group=root
WorkingDirectory=/opt/ride-converge
EnvironmentFile=/opt/ride-converge/.env
ExecStart=/root/miniconda3/envs/ride-converge/bin/python -m ride_converge.web.server --host 127.0.0.1 --port 8765
```

将服务文件安装并启动：

```bash
sudo cp deploy/systemd/ride-converge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ride-converge
sudo systemctl status ride-converge
```

如果启动失败，查看日志：

```bash
journalctl -u ride-converge -n 100 --no-pager
```

因为当前 Miniconda 安装在 `/root`，服务暂时需要以 root 运行。正式长期运行时，建议创建专用服务用户，将 Conda 安装到该用户主目录或 `/opt/miniconda3`，然后同步修改 `User`、`Group` 和 `ExecStart`，不要让公开 Web 服务长期拥有 root 权限。

## 二、配置域名、HTTPS 和 Nginx

在 DNS 服务商处新增：

```text
ride-converge.wenlei.wang  A  你的服务器公网 IPv4
```

请使用连字符 `-`，不要使用下划线 `_`。公开主机名、TLS 证书和微信域名校验对下划线的兼容性不可靠。

仓库提供了 `deploy/nginx/ride-converge.conf`。先申请该域名的有效 HTTPS 证书，核对证书路径，再启用配置：

```bash
sudo cp deploy/nginx/ride-converge.conf /etc/nginx/conf.d/
sudo nginx -t
sudo systemctl reload nginx
curl https://ride-converge.wenlei.wang/api/health
```

线上接口必须返回受信任的完整证书链，不能使用自签名证书。

## 三、配置微信公众平台

登录该 AppID 对应的小程序后台，在“开发管理 → 开发设置 → 服务器域名”中，把以下地址加入 `request` 合法域名：

```text
https://ride-converge.wenlei.wang
```

只填写域名，不附加 `/api/` 路径。配置生效可能需要短暂等待，之后重新编译小程序。

## 四、导入和调试

### 手机端交互

- 地图为主界面，顶部搜索框用于选择目的地，右侧支持缩放和路线全览。
- 底部面板支持收起、半屏和展开；上下滑动面板把手或点击按钮切换。
- 拖动面板顶部把手或“一起骑行”标题区域，地图高度会同步变化；表单内部上下滑动仍用于浏览地点列表。也可点击“看地图”直接收起面板。
- 点击骑友起点、途经点或终点进入统一的地点搜索页。
- 搜索结果显示地点名称、详细地址和分类；点击具体结果后才保存位置，不自动采用第一条结果。
- 搜索一次最多显示 20 条候选地点；没有结果时可修改关键词、城市或改用地图选点。
- 地图选点需要点击“确认此位置”；仅浏览、返回或取消不会修改原地点。
- 汇合方案在底部卡片中展示，可左右滑动或点击标签切换；地图同步绘制个人路线与绿色共同路段。
- 起点、途经点顺序或规划参数修改后，旧方案立即失效，需要重新计算。
- 没有符合条件的汇合点时，各自先骑到共同路线的第一个途经点，汇合后按剩余途经点顺序一起前往终点。页面统一显示“集合方案”和“集合点”，不显示“保底”标记；不会擅自重排或跳过途经点。
- 未添加途经点时，保底方案为分别前往最终目的地，并明确显示没有后续共同路段。
- 保底路线仍调用真实高德骑行接口。仅“无可行汇合点”触发保底，网络错误、密钥错误或路线不可达不会被掩盖。保底不保证满足原方向、走廊或绕行约束，绕行比例显示“未评估”。

保底响应的 `is_fallback` 为 `true`、`ranking` 为 `fallback_first_common_stop`；`routes.riders_gcj` 为各自到集合处的路线，`routes.shared_gcj` 为汇合后串联途经点和终点的共同路线。当前展示的是路线规划结果，不是小程序内的实时语音导航引擎。

### 本次版本更新部署

候选地点列表使用新增的 `POST /api/search/places`。更新小程序时，必须同时上传服务器的 `ride_converge/providers/amap.py` 和 `ride_converge/web/server.py`，然后重启服务：

```bash
sudo systemctl restart ride-converge
```

旧的 `/api/search` 接口保持兼容，原 Web 页面不受影响。微信开发者工具需要重新编译并上传包含 `miniprogram/assets/` 的完整小程序包。

### 开发者工具操作

1. 打开微信开发者工具，选择“导入项目”。
2. 项目目录选择仓库根目录 `ride-converge`。
3. 确认 AppID 为 `wx35c145cb4a63ae54`。
4. 确认 `miniprogram/config.js` 中的服务地址为 `https://ride-converge.wenlei.wang`。
5. 编译后分别测试地点搜索、地图选点、添加途经点、生成方案和切换推荐方案。

如果线上服务尚未部署，可临时把 `apiBaseUrl` 改为 `http://127.0.0.1:8765`，并只在开发者工具中开启“不校验合法域名、Web-view（业务域名）、TLS 版本以及 HTTPS 证书”。手机预览中的 `127.0.0.1` 指向手机自身，不能用于真机联调；真机测试应使用已部署的 HTTPS 域名。

## 五、上传与发布

1. 在开发者工具中点击“上传”，填写版本号和项目备注。
2. 登录微信公众平台，在“版本管理”中选择刚上传的开发版本。
3. 设置体验版，在真机上完成真实路线测试。
4. 提交微信审核；按页面实际用途填写服务类目、隐私说明和功能截图。
5. 审核通过后点击发布。

本项目不会自动登录或代替管理员上传版本。最终上传、审核和发布必须由该 AppID 的开发者或管理员在微信开发者工具与公众平台中完成。

## 发布前检查

- `https://ride-converge.wenlei.wang/api/health` 可公网访问。
- Nginx 到 `127.0.0.1:8765` 的反向代理正常。
- 微信后台已添加 `request` 合法域名。
- `.env` 和高德 Key 未进入小程序代码、Git 历史或日志。
- 高德控制台中的 Web 服务 Key 已限制可用服务和调用额度。
- Nginx 限流已启用，并结合实际访问量监控高德调用配额。
- 至少完成一次真实地点、真实骑行路线和多个途经点测试。
