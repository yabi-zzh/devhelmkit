# devhelmkit

> 跨平台 UI 自动化框架，当前聚焦 HarmonyOS。

[![PyPI version](https://img.shields.io/pypi/v/devhelmkit)](https://pypi.org/project/devhelmkit/)
[![PyPI downloads](https://img.shields.io/pypi/dm/devhelmkit)](https://pypi.org/project/devhelmkit/)
[![Python versions](https://img.shields.io/pypi/pyversions/devhelmkit)](https://pypi.org/project/devhelmkit/)
[![PyPI license](https://img.shields.io/pypi/l/devhelmkit)](https://pypi.org/project/devhelmkit/)
[![Publish](https://github.com/yabi-zzh/devhelmkit/actions/workflows/publish.yml/badge.svg)](https://github.com/yabi-zzh/devhelmkit/actions/workflows/publish.yml)
[![GitHub stars](https://img.shields.io/github/stars/yabi-zzh/devhelmkit)](https://github.com/yabi-zzh/devhelmkit)

[API 参考](api_reference.md)

## 概述

devhelmkit 为 HarmonyOS 设备提供 UI 自动化测试能力。通过 `hdc` 直连设备，无需任何测试框架运行时。

**核心目标：**

- **简洁 API**：`d(text="登录").click()`、`d.app_start()`、`d.dump_hierarchy()`
- **直连设备**：仅通过 `hdc` 通信，不依赖测试框架
- **跨平台抽象**：`BaseDriver` 契约 + 平台实现（HarmonyOS 已全功能可用，Android 预留）
- **高级能力**：鼠标、触控笔、指关节、触控板、多指手势

## 功能特性

- **选择器链**：`d(text="xx")` / `d(id="xx")` / `d.xpath("//Text")`
- **控件操作**：点击、长按、输入、拖拽、滑动、属性查询
- **控件集合**：通过 `count`、`all()`、`first()`、`last()` 批量处理匹配控件
- **条件等待**：等待控件可用、禁用、可点击，或通过 `wait_until()` 自定义状态条件
- **设备控制**：亮屏/熄屏、解锁、按键、旋转、截图
- **应用管理**：启动、停止、安装、卸载
- **高级手势**：完整鼠标操作、触控笔（带压力）、指关节敲击、多指
- **触控板**：多指滑动、滑动停顿
- **事件监听**：Toast 监听、UI 事件（对话框/窗口/组件）
- **WebView 自动化**：通过 chromedriver + selenium 测试应用内网页
- **图像匹配**：模板匹配（多尺度 + 颜色校验）和特征匹配（SIFT/ORB）
- **OCR**：通过 RapidOCR（ONNX Runtime）识别屏幕文本
- **双查找后端**：uitest（设备端 RPC）+ uitree（本地布局解析）
- **屏幕录制**：JPEG 帧捕获与 MP4 编码
- **资源管理**：自动清理 socket/端口转发，可选停止守护进程
- **网页版 UIViewer**：本地双端口 Web 服务，实时投屏、控件定位与操作录制
- **跨平台**：Windows / Linux / macOS，可配置 hdc 路径

## UIViewer 网页版控件查看器

UIViewer 提供本地 Web 界面，支持实时投屏、控件树查看和触控操作。

### 启动

```bash
devhelmkit-uiviewer
```

无需参数，启动后自动打开浏览器。每次启动使用系统分配的空闲端口，互不冲突。

开启性能排查日志（采集帧率、推流帧率、触控 RPC 耗时）：

```bash
devhelmkit-uiviewer --perf
```

### 两种采集模式

| 模式 | 截图来源 | 控件树来源 | 触控 | 说明 |
|------|---------|-----------|------|------|
| **单次 (snapshot)** | hdc snapshot_display | hdc dumpLayout 文件导出 | 禁用 | 不启动 RPC 和截图推流 |
| **实时 (live)** | uitest startCaptureScreen | dump_hierarchy rpc | 启用 down/move/up | 实时投屏 + 触控 |

### 功能

- 页面内选择/切换手机
- 模式切换：单次 (HDC) / 实时 (UITest)
- 截图上叠加控件 bounds，高亮 hover/selected 节点
- 右侧控件树和属性面板，属性值一键复制
- 为选中控件生成并切换 ID、文本、类型等 XPath 1.0 定位候选
- 录制点击、长按、输入、滑动和按键操作，生成可复制的 Python 自动化脚本
- 实时模式支持鼠标 down/move/up 映射为设备 touch
- 实时模式设备导航键：返回 / 主页 / 多任务
- 实时模式锁定画面后检视控件（锁定时重新抓取控件树，与锁定瞬间画面对应）
- 画面刷新：实时投屏为变化驱动，画面静止时可点击画面内刷新按钮唤醒一帧
- 关闭时清理 uitest 可选（默认保留）
- 单次模式手动刷新时，截图帧与控件树来自同一次刷新链路

### 端口

启动时自动分配两个系统空闲端口：

- **control_port**：页面、API、配置、touch 控制
- **jpeg_port**：JPEG/MJPEG 图片流

运行时端点按职责隔离：

| 端口 | 端点 | 职责 |
|------|------|------|
| control_port | `GET /`、`GET /index.html`、`GET /static/app.js` | 页面与静态资源 |
| control_port | `GET /api/runtime`、`GET /api/devices`、`GET /api/session?serial=...` | 运行时端口、设备列表、会话状态 |
| control_port | `GET /api/xpath?serial=...&node_id=...`、`GET /api/record/state?serial=...` | XPath 定位候选、操作录制状态 |
| control_port | `POST /api/session/select`、`POST /api/session/mode`、`POST /api/session/cleanup`、`POST /api/session/close` | 设备选择、模式切换、清理策略、关闭会话 |
| control_port | `POST /api/refresh`、`GET /api/hierarchy?serial=...`、`POST /api/touch` | 刷新帧与控件树、实时控件树、live 触控 |
| control_port | `POST /api/key`、`POST /api/live/refresh` | live 设备导航键、强制刷新一帧画面 |
| control_port | `POST /api/record/start`、`POST /api/record/stop`、`POST /api/record/action`、`POST /api/record/delete`、`POST /api/record/clear` | 开始/停止录制、记录/删除/清空脚本步骤 |
| jpeg_port | `GET /snapshot.jpg?serial=...&frame=...` | snapshot 单帧 JPEG；网页刷新链路读取 `/api/refresh` 缓存帧 |
| jpeg_port | `GET /stream.mjpeg?serial=...` | live MJPEG 图片流 |

浏览器不直连裸 TCP；图片只从 `jpeg_port` 拉取，控制 API 只走 `control_port`。

进程退出时只释放本次实例创建的端口和资源。

## 安装

### 前置条件

- **Python 3.8+**（Windows / Linux / macOS）
- **HarmonyOS 设备**，已开启开发者模式和 USB 调试
- **hdc**（HarmonyOS Device Connector）— 用于设备通信

#### 安装 hdc

hdc 随 HarmonyOS SDK 一起提供：

1. 下载 [HarmonyOS SDK](https://developer.huawei.com/consumer/cn/download/)（选择 Command Line Tools）
2. 解压后，hdc 位于 `sdk/<版本>/toolchains/` 目录
3. 将该目录添加到系统 `PATH`
4. 验证：

```bash
hdc -v
# HarmonyOS Device Connector vX.X.X
```

验证设备连接：

```bash
hdc list targets
# ABCD1234567890
```

### 安装 devhelmkit

#### 方式一：pip（推荐）

```bash
pip install devhelmkit
```

#### 方式二：源码安装

```bash
git clone https://github.com/yabi-zzh/devhelmkit.git
cd devhelmkit
pip install -e .
```

### 依赖

**核心依赖**（自动安装）：

| 包 | 用途 |
|----|------|
| `Pillow>=9.0.0` | 截图处理 |
| `lxml>=5.0.0` | 标准 XPath 1.0 控件树查询 |

> **基础安装即包含原生自动化能力**：控件查找/操作、设备控制、手势、事件监听、屏幕录制等核心功能无需任何额外依赖。

**可选依赖**（按需安装）：

| Extra | 安装命令 | 额外引入的包 | 功能范围 |
|-------|---------|-------------|---------|
| `cv` | `pip install devhelmkit[cv]` | `opencv-python-headless`, `numpy` | 图像匹配（模板 + 特征） |
| `ocr` | `pip install devhelmkit[ocr]` | `rapidocr-onnxruntime`, `opencv-python-headless`, `numpy` | OCR 文本识别（含图像匹配能力） |
| `webview` | `pip install devhelmkit[webview]` | `selenium` | WebView / 应用内浏览器自动化 |
| `all` | `pip install devhelmkit[all]` | 以上全部 | 全部能力（cv + ocr + webview） |
| `dev` | `pip install devhelmkit[dev]` | `pytest`, `pytest-cov`, `build`, `twine` | 开发 / 测试 / 发布工具链 |

> **依赖关系**：`ocr` 已包含 `cv` 的全部依赖（opencv + numpy），安装 `[ocr]` 后无需再装 `[cv]`。`[all]` 是 `cv` + `ocr` + `webview` 的超集。

## 快速开始

```python
import devhelmkit

# 自动发现并连接设备
d = devhelmkit.connect()

# 启动应用
d.app_start("com.huawei.hmos.settings")

# 查找并操作控件
d(text="搜索").click()
d(className="TextInput").input_text("devhelmkit")

# 截图
d.screenshot().save("screen.png")

# 导出控件树
hierarchy = d.dump_hierarchy()

# 关闭连接，释放 socket 和端口转发
d.close()
```

### 资源清理

使用 `with` 语句或 `try/finally` 确保资源释放：

```python
import devhelmkit

with devhelmkit.connect() as d:
    d.app_start("com.huawei.hmos.settings")
    d(text="搜索").click()
# 退出时自动调用 close()
```

关闭时同时停止设备端 uitest 守护进程（默认：保留以便复用）：

```python
# 方式一：运行时指定
d.close(stop_daemon=True)

# 方式二：通过配置
from devhelmkit.harmony.config import HarmonyDriverConfig

config = HarmonyDriverConfig(stop_daemon_on_close=True)
d = devhelmkit.connect(config=config)
```

启动时先清理残留守护进程再重启（默认复用已有进程；开启后可规避残留 daemon 版本不匹配或状态损坏导致的连接异常）：

```python
from devhelmkit.harmony.config import HarmonyDriverConfig

config = HarmonyDriverConfig(restart_daemon_on_setup=True)
d = devhelmkit.connect(config=config)
```

### 指定设备

```python
# 多设备时指定序列号
d = devhelmkit.connect(serial="1234567890ABCDEF")

# 显式指定平台
d = devhelmkit.connect(platform="harmony")
```

### 配置 hdc 路径

当 hdc 不在 `PATH` 中，或需要使用特定版本时：

```python
import devhelmkit
from devhelmkit.harmony.device.hdc import HdcDevice

# 全局设置（影响后续所有连接）
HdcDevice.set_hdc_path("/path/to/hdc")

d = devhelmkit.connect()
```

或通过配置：

```python
from devhelmkit.harmony.config import HarmonyDriverConfig

config = HarmonyDriverConfig(hdc_path="/path/to/hdc")
d = devhelmkit.connect(config=config)
```

## API 示例

### 控件操作

```python
# 等待控件出现
d(text="登录").wait(timeout=10)

# 存在时点击，未找到返回 False
d(text="跳过").click_if_exists(timeout=1)

# 批量处理匹配控件
items = d(className="ListItem")
print(items.count)
for item in items.all():
    print(item.get_text())
items.first().click()

# 等待控件状态或自定义条件
d(id="submit").wait_clickable(timeout=5)
d(id="status").wait_until(
    lambda info: info.get("text") == "完成",
    timeout=10,
)

# 输入文本
d(id="username").input_text("admin")

# 清空文本
d(id="username").clear_text()

# 长按
d(text="条目").long_click()

# 拖拽到另一控件
d(text="A").drag_to_component(d(text="B"))

# 获取属性
print(d(text="标题").info)
print(d(text="标题").bounds)
```

### 图像匹配

> 需要安装：`pip install devhelmkit[cv]`

```python
# 模板匹配（默认，快速）
rect = d.vision.find_image("icon.png")
if rect:
    print(f"找到，位置: {rect}")

# 特征匹配（抗缩放/旋转）
rect = d.vision.find_image("icon.png", mode="feature", threshold=0.7)

# 查找并点击
d.vision.touch_image("button.png")

# 检查是否存在
if d.vision.exists_image("logo.png"):
    print("Logo 已找到")

# 等待图像出现
d.vision.wait_image("loading_done.png", timeout=15)
```

### OCR

> 需要安装：`pip install devhelmkit[ocr]`

```python
# 查找并点击文本
d.vision.click_text("设置")

# 模糊匹配（归一化子串 + 相似度兜底，忽略大小写与空白）
d.vision.click_text("设置", fuzzy=True)

# 获取 OCR 结果含坐标
result = d.vision.find_text("登录")
if result:
    print(f"找到: {result.text} 位置: {result.bounds} 置信度: {result.confidence}")

# 识别区域内所有文本
results = d.vision.ocr(region=(100, 200, 500, 400))
for r in results:
    print(f"{r.text} @ {r.bounds} (置信度={r.confidence:.2f})")
```

### 手势

```python
# 滑动
d.swipe(100, 500, 100, 100)

# 双指滑动
d.two_finger_swipe((0, 400), (200, 400), (880, 400), (680, 400))

# 自定义手势
from devhelmkit.model.input import GestureAction

g = GestureAction()
g.add_step("move", 100, 200)
g.add_step("move", 200, 300)
d.inject_gesture(g, speed=1000)
```

### 鼠标

```python
# 左键点击
d.mouse_click((500, 500))

# 右键点击
d.mouse_click((500, 500), button_id=1)

# 滚轮
d.mouse_scroll((500, 500), "down", steps=3)

# 拖拽
d.mouse_drag((100, 100), (300, 300))
```

### 触控笔

```python
# 点击
d.pen_click((500, 500))

# 带压力长按
d.pen_long_click((500, 500), pressure=0.8)

# 方向滑动
d.pen_swipe("UP", distance=60)
```

### 事件监听

```python
# Toast 监听
d.start_listen_toast()
d(text="提交").click()
print("Toast:", d.get_latest_toast(timeout=3))

# 检查 Toast
if d.check_toast("保存成功", fuzzy="contains"):
    print("操作成功")
```

### 屏幕录制

方式一：手动控制

```python
# 开始录制
d.start_recording("/tmp/recording")

# ... 执行操作 ...

# 停止并编码为 MP4
video_path = d.stop_recording("/tmp/recording/output.mp4")
print(f"视频已保存: {video_path}")
```

方式二：上下文管理器（推荐）

```python
# 异常时自动停止录屏，资源必定释放
with d.record("/tmp/output.mp4") as rec:
    d(text="登录").click()
    d(text="密码").input_text("xxx")
# 退出 with 块时自动合成视频
print(f"视频已保存: {rec.video_path}")
```

### 设备控制

```python
# 亮屏/熄屏
d.wake_up_display()
d.close_display()

# 按键
from devhelmkit.model.keys import KeyCode

d.press_keycode(KeyCode.ENTER)  # 确认键

# 截图
img = d.screenshot()
img.save("capture.png")

# 安装应用
d.app_install("/path/to/app.hap")
```

### 应用管理

```python
# 启动应用（自动探测 main ability，无需手动指定 Ability 名）
d.app_start("com.example.app")

# 指定 Ability 启动
d.app_start("com.example.app", "EntryAbility")

# 强制重启（回桌面 → 停止 → 启动）
d.force_start_app("com.example.app")

# 强制重启并清除数据
d.force_start_app("com.example.app", clear_data=True)

# 停止 / 卸载 / 清除数据
d.app_stop("com.example.app")
d.app_uninstall("com.example.app")
d.clear_app_data("com.example.app")

# 查询应用信息
d.app_list()                    # 已安装应用列表
d.has_app("com.example.app")    # 是否已安装
d.app_current()                 # 当前前台应用 (package, ability)
d.get_app_info("com.example.app")  # 完整应用信息 dict
```

### 深链 / Schema

```python
# 网页 URL（自动用系统浏览器打开）
d.open_url("https://www.example.com")

# 应用深链（由系统选择处理方，如 kwai:// 触发快手App）
d.open_url("kwai://myprofile")

# 强制指定是否用系统浏览器
d.open_url("https://www.example.com", system_browser=False)
```

### WebView 自动化

> 需要安装：`pip install devhelmkit[webview]`

需下载与设备 WebView 版本匹配的 chromedriver：

```bash
# 方式一：使用内置下载脚本（推荐）
# 自动探测设备 WebView 版本并下载
python scripts/download_chromedriver.py --auto

# 指定版本号下载
python scripts/download_chromedriver.py 114 -o ./chromedriver

# 查看可用版本
python scripts/download_chromedriver.py --list
```

或手动下载后按以下结构放置：

```text
chromedriver_search_path/
├── chromedriver_114/
│   ├── chromedriver.exe      # Windows
│   ├── chromedriver          # Linux
│   └── chromedriver.mac      # macOS
└── chromedriver_132/
    ├── chromedriver.exe
    ├── chromedriver
    └── chromedriver.mac
```

```python
# 连接应用 WebView
wv = d.webview(
    "com.huawei.hmos.browser",
    chromedriver_search_path="/path/to/chromedriver_search_path"
)

# 通过 selenium webdriver 操作
wv.driver.get("https://www.example.com")
wv.driver.find_element("id", "search").send_keys("devhelmkit")

# 释放资源
wv.close()
```

## 架构

```text
devhelmkit/                # 仓库根
├── src/devhelmkit/        # 包源码（src layout）
│   ├── core/              # 跨平台契约
│   │   ├── base_driver.py     # BaseDriver：设备驱动契约
│   │   ├── base_component.py  # BaseComponent：控件契约
│   │   ├── base_window.py     # BaseWindow：窗口契约
│   │   ├── selector_spec.py   # SelectorSpec：纯数据选择器
│   │   └── vision/            # 图像匹配 + OCR（平台无关）
│   │       ├── image_matcher.py    # OpenCV 模板 + 特征匹配
│   │       ├── ocr_engine.py       # RapidOCR 封装
│   │       └── vision_extension.py # d.vision 命名空间
│   ├── model/             # 纯数据类型（Rect / KeyCode / GestureAction / ...）
│   ├── harmony/           # HarmonyOS 平台实现
│   │   ├── driver.py          # 平台驱动门面
│   │   ├── config.py          # HarmonyDriverConfig
│   │   ├── device/            # hdc 命令封装 + RPC 通道
│   │   ├── rpc/               # 二进制 RPC 协议 + 远程对象管理
│   │   ├── finder/            # 控件查找（uitest + uitree 双后端）
│   │   ├── agent/             # 设备端 uitest 守护进程管理
│   │   └── webview/           # WebView 自动化（chromedriver + selenium）
│   ├── uiviewer/          # 网页版控件查看器（双端口 Web 服务）
│   ├── android/           # Android 平台（预留）
│   ├── utils/             # 工具（日志 / 重试 / 超时）
│   └── assets/so/         # 设备端 agent.so 二进制
└── scripts/           # 辅助脚本（chromedriver 下载工具）
```

完整 API 参考见 [api_reference.md](api_reference.md)。

## 开发

### 代码结构约定

- `core/` 不得依赖平台实现
- `model/` 无内部依赖，可跨平台复用
- 平台实现按 `device/`、`rpc/`、`finder/` 组织
- RPC 层不感知 UI 对象；设备通道不理解控件定位

## 贡献

欢迎提交 Issue 和 Pull Request。

- **提交 Issue**：请使用对应模板（[Bug 报告](.github/ISSUE_TEMPLATE/bug_report.yml) / [功能请求](.github/ISSUE_TEMPLATE/feature_request.yml)），提交前先搜索[已有 Issue](https://github.com/yabi-zzh/devhelmkit/issues)避免重复。安全问题请勿公开提交，参见 [SECURITY.md](SECURITY.md)。
- **提交 Pull Request**：请阅读[贡献指南](CONTRIBUTING.md)，遵循代码分层约束与注释规范，并填写 PR 模板。

参与本项目请遵守[行为准则](CODE_OF_CONDUCT.md)。版本变更记录见 [CHANGELOG.md](CHANGELOG.md)。

## 许可证

[Apache License 2.0](LICENSE)