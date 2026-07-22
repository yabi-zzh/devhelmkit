# API 参考

> **devhelmkit** — 跨平台 UI 自动化框架，当前聚焦 HarmonyOS。

本文档列出 devhelmkit 的完整公开 API。

- 跨平台通用 API 由 `BaseDriver` / `BaseComponent` / `BaseWindow` 定义
- 平台特有 API 由驱动子类扩展（当前为 `HarmonyDriver`）
- 图像匹配与 OCR 通过 `d.vision` 命名空间访问，需按需安装可选依赖

## 目录

- [入口](#入口)
- [跨平台通用 API](#跨平台通用-api)
  - [生命周期](#生命周期)
  - [设备信息](#设备信息)
  - [屏幕操作](#屏幕操作)
  - [选择器](#选择器)
  - [应用管理](#应用管理)
  - [坐标操作](#坐标操作)
  - [实时触控](#实时触控)
  - [按键](#按键)
  - [Shell](#shell)
  - [截图与录制](#截图与录制)
  - [UI 树](#ui-树)
  - [等待](#等待)
  - [窗口](#窗口)
  - [文件操作](#文件操作)
  - [控件查找](#控件查找)
  - [图像识别](#图像识别)
  - [OCR 文本识别](#ocr-文本识别)
  - [文本输入辅助](#文本输入辅助)
  - [手势注入](#手势注入)
  - [手势导航](#手势导航)
  - [坐标转换](#坐标转换)
- [控件 API](#控件-api)
  - [点击](#点击)
  - [集合](#集合)
  - [文本](#文本)
  - [状态](#状态)
  - [信息](#信息)
  - [布尔属性](#布尔属性)
  - [拖拽](#拖拽)
  - [缩放](#缩放)
  - [滚动](#滚动)
  - [关系选择器](#关系选择器)
- [HarmonyOS 特有 API](#harmonyos-特有-api)
  - [应用安装与卸载](#应用安装与卸载)
  - [屏幕控制（鸿蒙）](#屏幕控制鸿蒙)
  - [文本输入（鸿蒙）](#文本输入鸿蒙)
  - [组件状态](#组件状态)
  - [表冠（穿戴设备）](#表冠穿戴设备)
  - [鼠标](#鼠标)
  - [触控笔](#触控笔)
  - [指关节](#指关节)
  - [多指手势](#多指手势)
  - [触控板](#触控板)
  - [事件监听](#事件监听)
  - [WebView](#webview)
- [数据类型](#数据类型)
  - [Rect](#rect)
  - [Point](#point)
  - [BaseWindow](#basewindow)
  - [GestureAction](#gestureaction)
  - [InputDevice](#inputdevice)
  - [MouseButton](#mousebutton)
  - [KeyCode](#keycode)
  - [OcrResult](#ocrresult)
  - [SelectorSpec](#selectorspec)
  - [HarmonyDriverConfig](#harmonydriverconfig)
- [异常体系](#异常体系)

---

## 入口

### `devhelmkit.connect(serial=None, platform="auto", config=None, log_level=None, **kwargs) -> BaseDriver`

连接设备并返回驱动实例。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| serial | str | 否 | 设备序列号，`None` 时自动发现首个可用设备 |
| platform | str | 否 | `"auto"` / `"harmony"` / `"android"` |
| config | - | 否 | 平台专用配置对象（如 `HarmonyDriverConfig`） |
| log_level | int | 否 | 日志级别，`None` 默认 INFO |
| **kwargs | - | 否 | 平台特定参数，覆盖 config 同名字段 |

**返回值：** `BaseDriver`（具体平台子类）

**异常：**
- `DeviceNotFoundError` — 未检测到可连接设备
- `DeviceConnectError` — 设备连接失败
- `PlatformNotSupportedError` — 平台不支持

```python
import devhelmkit

d = devhelmkit.connect()
```

---

## 跨平台通用 API

以下方法由 `BaseDriver` 定义，所有平台实现均提供。

### 生命周期

#### `close(stop_daemon=None) -> None`

关闭驱动，释放连接资源。支持上下文管理器（`with` 语句）。

> `stop_daemon` 参数为 HarmonyOS 平台扩展，`BaseDriver` 契约中 `close()` 无参数。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| stop_daemon | bool | None | 关闭时是否停止设备端 uitest 守护进程。`None` 使用配置默认值 |

```python
with devhelmkit.connect() as d:
    d.click(100, 100)
# 自动调用 close()
```

#### `device_sn -> str`

设备序列号（属性）。

#### `platform -> str`

平台标识：`"harmony"` / `"android"`（属性）。

---

### 设备信息

#### `info -> Dict[str, Any]`

设备基本信息：品牌、型号、系统版本等（属性）。

#### `get_display_size() -> Tuple[int, int]`

屏幕分辨率 `(width, height)`。

#### `get_display_rotation() -> int`

当前屏幕方向。

#### `set_display_rotation(rotation: int) -> None`

设置屏幕方向。

#### `set_display_rotation_enabled(enabled: bool) -> None`

自动旋转开关。

#### `get_device_type() -> str`

设备类型：`phone` / `tablet` / `2in1` / `wearable` / ...

#### `get_device_model() -> str`

设备型号。

#### `get_brand() -> str`

设备品牌。

#### `get_abi() -> str`

CPU ABI（如 `arm64-v8a`）。

#### `get_os_type() -> str`

操作系统类型标识。

#### `get_system_version() -> str`

操作系统版本号。

#### `get_api_level() -> str`

API 级别。

---

### 屏幕操作

#### `screen_on() -> None`

亮屏（唤醒屏幕）。

#### `screen_off() -> None`

熄屏。

#### `is_screen_on() -> bool`

屏幕是否点亮。

#### `is_screen_locked() -> bool`

屏幕是否锁屏。

#### `unlock() -> None`

解锁设备（亮屏 + 上滑/回车解除锁屏）。

#### `set_sleep_time(seconds: float) -> None`

设置熄屏时间（秒）。

#### `restore_sleep_time() -> None`

恢复默认熄屏时间。

---

### 选择器

#### `__call__(**kwargs) -> BaseComponent`

U2 风格选择器，返回控件对象。

支持条件：`text` / `text_contains` / `text_starts_with` / `text_ends_with` / `text_matches` / `id` / `resourceId` / `className` / `description` / `desc` / `key` / `type` / `instance`（第 N 个匹配，0 起）。

> `index` 与 `text_matches_flags` 在 HarmonyOS 平台不受支持，传入会抛 `DevhelmError`；请分别改用 `instance` 和正则内联 flags（如 `(?i)`）。

```python
d(text="登录").click()
d(id="username").input_text("admin")
d(className="Button", textContains="提交")
```

#### `xpath(xpath: str) -> BaseComponent`

XPath 选择器，返回控件对象。HarmonyOS 使用 `lxml` 标准 XPath 1.0 引擎查询当前控件树，支持属性谓词、位置、层级和组合表达式。命中节点会按 `bounds` 精确锚定回设备端 Component，因此可以继续执行点击、输入、文本读取等控件操作。

```python
d.xpath("//Text[@text='标题']").click()
d.xpath("(//Button[@enabled='true'])[2]").get_text()
d.xpath("//List/*[contains(@text, '设置')]").click()
```

---

### 应用管理

#### `app_start(package, activity=None, params="", wait_time=1) -> None`

启动应用。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| package | str | — | 应用包名 |
| activity | str | None | Activity（Android）/ Ability（鸿蒙） |
| params | str | "" | 附加启动参数 |
| wait_time | float | 1 | 启动后等待秒数 |

#### `app_stop(package, wait_time=0.5) -> None`

停止应用。

#### `app_current() -> Tuple[Optional[str], Optional[str]]`

获取当前前台应用 `(package, activity)`。位于桌面或读取失败时返回 `(None, None)`。

#### `app_list() -> List[str]`

已安装应用包名列表。

#### `has_app(package: str) -> bool`

查询是否已安装应用。

#### `clear_app_data(package: str) -> None`

清除应用数据。

---

### 坐标操作

#### `click(x: int, y: int) -> None`

坐标点击。

#### `long_click(x: int, y: int, duration: float = 0.5) -> None`

坐标长按。

#### `double_click(x: int, y: int) -> None`

坐标双击。

#### `swipe(x1, y1, x2, y2, duration=0.5) -> None`

从 `(x1, y1)` 滑动到 `(x2, y2)`。

#### `swipe_dir(direction, distance=60, area=None, speed=None) -> None`

方向滑动。

| 参数 | 说明 |
|------|------|
| direction | `"UP"` / `"DOWN"` / `"LEFT"` / `"RIGHT"` |
| distance | 滑动距离（像素） |
| area | 滑动区域 |
| speed | 滑动速度 |

#### `drag(x1, y1, x2, y2, duration=0.5) -> None`

拖拽。

#### `fling(direction, distance=50, area=None, speed="fast") -> None`

抛滑（快速惯性滑动）。

---

### 实时触控

#### `touch_down(x: int, y: int) -> None`

按下触控点。

#### `touch_move(x: int, y: int) -> None`

移动触控点（需先 `touch_down`）。

#### `touch_up(x: int, y: int) -> None`

抬起触控点（结束触控序列）。

```python
d.touch_down(100, 100)
d.touch_move(200, 200)
d.touch_up(200, 200)
```

---

### 按键

#### `press(key: str) -> None`

语义按键：`"back"` / `"home"` / `"power"` / `"volume_up"` / ...

#### `press_keycode(keycode: int) -> None`

按下平台原始按键码。

#### `go_home() -> None`

返回桌面。

#### `go_back() -> None`

返回上一级。

#### `go_recent_task() -> None`

进入多任务界面。

#### `press_power() -> None`

按下电源键。

#### `press_combination_key(key1: int, key2: int, key3=None) -> None`

按下组合键（支持 2 键或 3 键）。

---

### Shell

#### `shell(cmd: str, timeout: float = 60) -> str`

在设备上执行 shell 命令，返回回显内容。

---

### 截图与录制

#### `screenshot(filename=None, area=None) -> Union[Image, str, None]`

截图。

| 参数 | 说明 |
|------|------|
| filename | `None` 返回 `PIL.Image`；指定路径则保存到文件并返回路径 |
| area | 区域截图（`Rect` / `SelectorSpec` / `None`） |
| 返回 | 失败返回 `None` |

#### `start_recording(output_dir: str) -> None`

开始录屏，JPEG 帧存放在 `output_dir/frames/`。

#### `stop_recording(output_path: str) -> str`

停止录屏并编码为视频。

**返回值：** 实际保存的视频文件路径。

---

### UI 树

#### `dump_hierarchy(source="rpc", filename=None) -> Union[dict, str, None]`

导出控件树。

| 参数 | 说明 |
|------|------|
| source | `"rpc"` 走 uitest RPC（默认）；`"hdc"` 走 hdc shell |
| filename | `None` 返回解析后 `dict`；指定路径则保存 JSON 并返回路径 |
| 返回 | 失败返回 `None` |

---

### 等待

#### `wait(seconds: float) -> None`

强制等待指定秒数。

#### `wait_for_idle(idle_time=0.7, timeout=10) -> None`

等待 UI 进入空闲状态。

#### `implicitly_wait(seconds: float) -> None`

设置隐式等待超时。

---

### 窗口

#### `window -> BaseWindow`

当前窗口对象（属性）。

#### `get_windows() -> List[BaseWindow]`

获取所有窗口。

---

### 文件操作

#### `push_file(local_path, remote_path, timeout=60) -> None`

推送文件到设备。

#### `pull_file(remote_path, local_path=None, timeout=60) -> str`

从设备拉取文件，返回实际保存的本地路径。`local_path` 为 `None` 时保存到临时文件，路径通过返回值获取。

#### `has_file(path: str) -> bool`

查询设备端文件是否存在。

---

### 控件查找

#### `find_component(target, scroll_target=None) -> Optional[BaseComponent]`

查找单个控件。未传 `scroll_target` 时返回惰性 `UiObject`（对齐 U2，操作时再定位）；传入 `scroll_target` 时在对应可滚动容器内执行 `scroll_search`，未找到返回 `None`。

```python
d.find_component({"text": "拒绝"}, scroll_target={"type": "Scroll"})
# 等价于：
d(type="Scroll").scroll_search(text="拒绝")
```

#### `find_all_components(target) -> List[BaseComponent]`

查找所有匹配控件。

#### `get_component_bound(target) -> Optional[Any]`

获取控件边界 `Rect`，未找到返回 `None`。

#### `get_component_property(target, name: str) -> Any`

获取控件指定属性。

支持属性名：`id` / `text` / `key` / `type` / `enabled` / `focused` / `clickable` / `scrollable` / `checked` / `checkable` / `description` / `selected` / `bounds`。

---

### 图像识别

> 需要安装可选依赖：`pip install devhelmkit[cv]`

所有图像识别方法通过 `d.vision` 命名空间访问。

#### `d.vision.find_image(template, region=None, threshold=0.8, timeout=None, mode="template", min_match_count=8, scale_range=None) -> Optional[Rect]`

查找图像位置，返回 `Rect` 或 `None`。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| template | str / Image / bytes | — | 模板图片（路径 / PIL.Image / bytes） |
| region | - | None | 查找区域（`Rect` / dict / tuple / 控件 / `None` 为全屏） |
| threshold | float | 0.8 | 匹配阈值（0–1），低于此值视为未匹配 |
| timeout | float | None | 超时秒，`None` 走全局隐式等待 |
| mode | str | "template" | `"template"` 模板匹配；`"feature"` 特征匹配 |
| min_match_count | int | 8 | feature 模式下最少有效特征点数 |
| scale_range | (float, float) | None | 多尺度搜索缩放区间，`None` 用默认 3 档 (0.9, 1.0, 1.1)；给定 (lo, hi) 在区间均匀采样 5 档 |

**template 模式：** 单尺度快路径 → 多尺度兜底 → 颜色二次校验。

**feature 模式：** SIFT（优先）或 ORB（兜底）+ FLANN/BFMatcher + RANSAC 单应性矩阵。适用于目标存在缩放、旋转或轻微透视变化的场景。

```python
# 模板匹配（默认，快速）
rect = d.vision.find_image("icon.png")

# 特征匹配（抗缩放/旋转）
rect = d.vision.find_image("icon.png", mode="feature", threshold=0.7)
```

#### `d.vision.touch_image(template, region=None, threshold=0.8, timeout=None, mode="template", min_match_count=8, scale_range=None) -> bool`

查找并点击图像，成功返回 `True`。

#### `d.vision.exists_image(template, region=None, threshold=0.8, mode="template", min_match_count=8, scale_range=None) -> bool`

检查图像是否存在（单次检测，不等待）。

#### `d.vision.wait_image(template, region=None, threshold=0.8, timeout=10, mode="template", min_match_count=8, scale_range=None) -> bool`

等待图像出现，超时内找到返回 `True`。

---

### OCR 文本识别

> 需要安装可选依赖：`pip install devhelmkit[ocr]`

#### `d.vision.ocr(region=None, timeout=None) -> List[OcrResult]`

识别屏幕文本，返回 `OcrResult` 列表。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| region | - | None | 识别区域（类型同图像识别） |
| timeout | float | None | 超时秒 |

**提示：** 限定 `region` 可显著提升速度（全屏 ~800ms → 区域 ~100ms）。

#### `d.vision.find_text(text, region=None, fuzzy=False, index=1, timeout=None) -> Optional[OcrResult]`

通过 OCR 查找文本位置，返回 `OcrResult` 或 `None`。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| text | str | — | 目标文本 |
| region | - | None | 查找区域 |
| fuzzy | bool | False | `True` 归一化子串匹配 + 相似度兜底（忽略大小写与空白），`False` 精确匹配 |
| index | int | 1 | 匹配到多个结果时选择第几个（1-based） |
| timeout | float | None | 超时秒 |

#### `d.vision.click_text(text, region=None, fuzzy=False, index=1, timeout=None) -> bool`

查找并点击文本，成功返回 `True`。

```python
# 查找并点击"设置"
d.vision.click_text("设置")

# 模糊匹配
d.vision.click_text("设置", fuzzy=True)

# 获取 OCR 结果含坐标
result = d.vision.find_text("登录")
if result:
    print(f"找到: {result.text} 位置: {result.bounds} 置信度: {result.confidence}")
```

---

### 文本输入辅助

#### `hide_keyboard() -> None`

隐藏软键盘。

#### `input_text_on_cursor(text: str) -> None`

在当前光标处输入文本（不依赖控件定位）。

#### `move_cursor(direction: str, times: int = 1) -> None`

移动输入框光标。

| direction | 说明 |
|-----------|------|
| `"LEFT"` / `"RIGHT"` | 左右移动 |
| `"UP"` / `"DOWN"` | 上下移动 |
| `"BEGIN"` / `"END"` | 行首 / 行尾 |

---

### 手势注入

#### `inject_gesture(gesture, speed=2000) -> None`

注入自定义手势。`gesture` 为 `GestureAction` 实例。

---

### 手势导航

#### `swipe_to_home(times=1) -> None`

屏幕底端上滑回到桌面（需开启手势导航）。

#### `swipe_to_back(side="right", times=1, height=0.5) -> None`

侧滑返回。

| 参数 | 说明 |
|------|------|
| side | `"LEFT"` / `"RIGHT"`（默认 `"right"`） |
| times | 滑动次数 |
| height | 屏幕高度比例（0.0–1.0） |

#### `swipe_to_recent_task() -> None`

底端上滑停顿进入多任务界面。

---

### 坐标转换

#### `to_abs_pos(x: float, y: float) -> Tuple[int, int]`

比例坐标（0.0–1.0）转绝对像素坐标。

---

## 控件 API

以下方法由 `BaseComponent` 定义，适用于通过 `d(text=...)`、`d.xpath(...)`、`d.find_component(...)` 等返回的控件对象。

### 点击

#### `click(timeout=None) -> None`

点击控件。

#### `long_click(duration=0.5, timeout=None) -> None`

长按控件。

#### `double_click(timeout=None) -> None`

双击控件。

#### `click_if_exists(timeout=0) -> bool`

控件存在时点击并返回 `True`，未找到时返回 `False`。`timeout=0` 时仅检查一次。

#### `refresh() -> None`

手动失效缓存的控件引用，下次操作时重新查找。适用于控件可能已被回收或重建的场景。

---

### 集合

集合方法会按当前选择器批量查询控件；返回的控件对象可继续执行点击、输入和属性读取等操作。

#### `count -> int`

当前匹配的控件数量（属性）。

#### `all() -> List[BaseComponent]`

返回当前匹配的全部控件对象；无匹配时返回空列表。

#### `first() -> BaseComponent`

返回第一个匹配控件。无匹配时抛出 `ComponentNotFoundError`。

#### `last() -> BaseComponent`

返回最后一个匹配控件。无匹配时抛出 `ComponentNotFoundError`。

```python
items = d(className="ListItem")
print(items.count)
for item in items.all():
    print(item.get_text())
items.first().click()
items.last().click()
```

---

### 文本

#### `set_text(text, timeout=None) -> None`

输入文本。默认（`clear_text_before_input=True`）先清空再输入，即"替换"语义；设为 `False` 则在现有文本上追加。

#### `get_text(timeout=None) -> str`

获取控件文本。

#### `clear_text(timeout=None) -> None`

清空文本。`clear_text_mode="once"` 走设备端 `clearText`；`"select_all"` 全选后按删除键清空，用于部分 `clearText` 不生效的输入框。

#### `input_text(text, timeout=None) -> None`

`set_text` 别名。

---

### 状态

#### `exists() -> bool`

控件是否存在。

#### `wait(timeout: float) -> bool`

等待控件出现，找到返回 `True`。

#### `wait_gone(timeout: float) -> bool`

等待控件消失，消失返回 `True`。

#### `wait_enabled(timeout=None) -> bool`

等待控件变为可用，条件满足返回 `True`，超时返回 `False`。`timeout=None` 时使用驱动的隐式等待时长。

#### `wait_disabled(timeout=None) -> bool`

等待控件变为禁用，条件满足返回 `True`，超时返回 `False`。`timeout=None` 时使用驱动的隐式等待时长。

#### `wait_clickable(timeout=None) -> bool`

等待控件变为可点击，条件满足返回 `True`，超时返回 `False`。`timeout=None` 时使用驱动的隐式等待时长。

#### `wait_until(condition, timeout=None) -> bool`

重复读取控件 `info`，直到 `condition(info)` 返回真值。条件满足返回 `True`，超时返回 `False`；控件暂未出现时会继续等待。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| condition | `Callable[[Dict[str, Any]], bool]` | — | 接收当前控件信息并返回真值的函数 |
| timeout | `Optional[float]` | `None` | 超时秒数，`None` 使用驱动的隐式等待时长；不能为负数 |

```python
d(id="submit").wait_clickable(timeout=5)
d(id="status").wait_until(
    lambda info: info.get("text") == "完成",
    timeout=10,
)
```

---

### 信息

#### `info -> Dict[str, Any]`

控件信息：`text` / `id` / `type` / `enabled` / `focused` / `selected` / `clickable` / `long_clickable` / `scrollable` / `checkable` / `checked` / `description` / `bounds`（属性）。

#### `bounds -> Rect`

控件坐标 `Rect(left, top, right, bottom)`（属性）。

#### `center() -> Tuple[int, int]`

控件中心点 `(x, y)`。

#### `get_attribute(name: str, timeout=None) -> Any`

获取指定属性。

#### `screenshot(filename=None) -> Union[Image, str, None]`

控件截图。

#### `description -> str`

`description` 属性（属性）。

#### `get_hint(timeout=None) -> str`

获取 `hint` 属性。

#### `get_all_properties(timeout=None) -> dict`

获取所有属性，返回 dict。

#### `get_original_text(timeout=None) -> str`

获取原始文本。

---

### 布尔属性

#### `is_long_clickable -> bool`

是否可长按（属性）。

#### `is_checked -> bool`

是否已选中（属性）。

#### `is_checkable -> bool`

是否可选中（属性）。

#### `is_selected -> bool`

是否处于选中态（属性）。

---

### 拖拽

#### `drag_to(x: int, y: int, timeout=None) -> None`

拖拽到指定坐标。

#### `drag_to_component(other: BaseComponent, timeout=None) -> None`

拖拽到另一控件。内部先将目标控件解析为设备端引用再调用 `Component.dragTo`。

---

### 缩放

#### `pinch_in(scale=0.5, timeout=None) -> None`

控件上捏合缩小。

#### `pinch_out(scale=1.5, timeout=None) -> None`

控件上捏合放大。

---

### 滚动

#### `scroll_search(target, vertical=True, offset=None, direction=None, max_swipes=20, speed=600, native=False) -> Optional[BaseComponent]`

在当前可滚动容器内滚动查找子控件。默认走**客户端定向滑动查找**；命中返回已绑定引用的控件，未命中返回 `None`。

```python
# 上滑查找下方项（默认 direction="up"）
item = d(type="List").scroll_search(text="隐私和安全", direction="up")
# 下滑查找上方项
item = d(type="List").scroll_search(text="WLAN", direction="down", max_swipes=15)
# 设备端原生（无方向，目标不存在时可能来回扫较久）
item = d(type="List").scroll_search(text="系统", native=True)
```

| 参数 | 说明 |
|------|------|
| `direction` | `up`/`down`/`left`/`right`，表示**手指滑动方向**；默认 `up`（上滑露出下方内容）。`native=True` 时忽略 |
| `max_swipes` | 客户端滑动最大次数，防止空扫 |
| `native` | `True` 走设备端 `Component.scrollSearch`（仅 `vertical`/`offset`，**不能指定方向**） |
| `vertical`/`offset` | 仅 `native=True` 时生效；`offset` 为设备协议滚动偏移比例（0–100） |

`target` 支持 `str` / `dict` / `SelectorSpec` / `UiObject`，也可直接传选择器关键字参数。复杂 xpath、`instance` 在 `native=True` 时无法下推，会抛 `DevhelmError`。

#### `scroll_to_top(speed=600, timeout=None) -> None`

滚动到顶部。

#### `scroll_to_bottom(speed=600, timeout=None) -> None`

滚动到底部。

---

### 关系选择器

#### `child(**kwargs) -> BaseComponent`

获取子控件。

#### `sibling(**kwargs) -> BaseComponent`

获取兄弟控件。

> HarmonyOS 平台不支持 `sibling` 关系（设备端 On API 无对应能力），调用会抛 `DevhelmError`。请改用 `after()` / `before()` 或 `parent().child()` 表达。

#### `after(**kwargs) -> BaseComponent`

获取之后的控件。

#### `before(**kwargs) -> BaseComponent`

获取之前的控件。

```python
# 在容器内查找子 Button
d(text="设置").child(className="Button")

# 查找某控件之后的 Text（sibling 在 HarmonyOS 不受支持，用 after/before 替代）
d(id="title").after(className="Text")
```

---

## HarmonyOS 特有 API

以下方法由 `HarmonyDriver` 扩展提供，仅鸿蒙平台可用。

### 配置访问

#### `config -> HarmonyDriverConfig`

当前驱动配置对象（属性）。

#### `update_config(**kwargs) -> None`

运行时更新配置字段，未知字段抛 `DehelmError`。

```python
d.update_config(screenshot_mode="stream", implicit_wait=20)
```

### 应用安装与卸载

#### `app_install(path: str, options: str = "") -> None`

通过 `bm install` 安装应用。

| 参数 | 说明 |
|------|------|
| path | 安装包路径（`.hap` / `.hsp`） |
| options | 附加安装选项（如 `-r` 覆盖安装） |

#### `app_uninstall(package: str) -> None`

通过 `bm uninstall` 卸载应用。

---

### 屏幕控制（鸿蒙）

#### `wake_up_display() -> None`

唤醒屏幕（点亮显示）。

#### `close_display() -> None`

关闭显示（息屏）。

---

### 文本输入（鸿蒙）

#### `clear_text_on_cursor() -> None`

清空当前光标所在输入框的文本。

---

### 组件状态

#### `switch_component_status(target, checked: bool) -> None`

切换开关类组件状态。

| 参数 | 说明 |
|------|------|
| target | 控件或选择器 |
| checked | `True` 打开，`False` 关闭 |

---

### 表冠（穿戴设备）

#### `rotate_crown(steps: int, speed: Optional[int] = None) -> None`

旋转表冠（穿戴设备专用）。

| 参数 | 说明 |
|------|------|
| steps | 旋转角度（正数顺时针，负数逆时针） |
| speed | 旋转速度（可选） |

---

### 鼠标

#### `mouse_click(pos, button_id=0, key1=None, key2=None) -> None`

鼠标点击。

| 参数 | 说明 |
|------|------|
| pos | 点击位置 `(x, y)` 或 `{"x": ..., "y": ...}` |
| button_id | 0=左键，1=右键，2=中键 |
| key1 | 组合键1（如 Ctrl=2072） |
| key2 | 组合键2 |

#### `mouse_double_click(pos, button_id=0) -> None`

鼠标双击。

#### `mouse_long_click(pos, button_id=0, press_time=1.5) -> None`

鼠标长按。`press_time` 为按住时长（秒）。

#### `mouse_scroll(pos, direction, steps, key1=None, key2=None) -> None`

鼠标滚轮滚动。

| 参数 | 说明 |
|------|------|
| direction | `"up"` 向上 / `"down"` 向下 |
| steps | 滚动步数 |

#### `mouse_move_to(pos) -> None`

鼠标光标瞬移到指定位置。

#### `mouse_move(start, end, speed=3000) -> None`

鼠标沿轨迹从起点移动到终点。

#### `mouse_drag(start, end, speed=3000) -> None`

鼠标拖拽。

---

### 触控笔

#### `pen_click(target, offset=None) -> None`

触控笔点击。`target` 可为坐标或控件，`offset` 为相对偏移 `(dx, dy)`。

#### `pen_double_click(target, offset=None) -> None`

触控笔双击。

#### `pen_long_click(target, offset=None, pressure=None) -> None`

触控笔长按。`pressure` 为笔压力值 0.0–1.0。

#### `pen_swipe(direction, distance=60, area=None, pressure=None, duration=0.3) -> None`

触控笔方向滑动。

| 参数 | 说明 |
|------|------|
| direction | `"UP"` / `"DOWN"` / `"LEFT"` / `"RIGHT"` |
| distance | 滑动距离（像素） |
| duration | 滑动时长（秒） |

#### `pen_slide(start, end, area=None, pressure=None, duration=0.3) -> None`

触控笔精确滑动（起止坐标）。

#### `pen_drag(start, end, area=None, pressure=None, press_time=1.5, duration=0.5) -> None`

触控笔拖拽（按住后移动）。

| 参数 | 说明 |
|------|------|
| press_time | 起点按住时长（秒） |
| duration | 移动到终点的时长（秒） |
| pressure | 笔压力值 0.0–1.0 |

#### `pen_inject_gesture(gesture, pressure=None, speed=2000) -> None`

触控笔自定义手势。

---

### 指关节

#### `knuckle_knock(targets: list, times: int = 2) -> None`

指关节敲击（常用于截屏等快捷操作）。

| 参数 | 说明 |
|------|------|
| targets | 敲击位置列表，1–2 个点 `[(x, y), ...]` |
| times | 敲击次数 |

#### `inject_knuckle_gesture(gesture, speed=2000) -> None`

指关节自定义手势。

---

### 多指手势

#### `inject_multi_finger_gesture(gestures: List[GestureAction], speed=2000) -> None`

多指手势，每个 `GestureAction` 代表一指轨迹。

#### `two_finger_swipe(s1, e1, s2, e2, duration=0.5) -> None`

双指滑动。

| 参数 | 说明 |
|------|------|
| s1 / e1 | 第一指起止坐标 |
| s2 / e2 | 第二指起止坐标 |
| duration | 滑动时长（秒） |

#### `multi_finger_touch(points: List[tuple], duration=0.1) -> None`

多指同时点击。`points` 为各指按下坐标 `[(x, y), ...]`。

---

### 触控板

#### `touchpad_swipe(direction, fingers=3, speed=None) -> None`

触控板多指滑动。

| 参数 | 说明 |
|------|------|
| direction | `"UP"` / `"DOWN"` / `"LEFT"` / `"RIGHT"` |
| fingers | 手指数（2–4） |
| speed | 滑动速度（可选） |

#### `touchpad_swipe_and_hold(direction, fingers=3, speed=None) -> None`

触控板多指滑动后停顿（`stay=true`）。

---

### 事件监听

#### `start_listen_toast() -> None`

开始 Toast 监听（once 模式，触发一次后自动移除）。

#### `get_latest_toast(timeout: float = 3.0) -> str`

获取最新 Toast 文本。阻塞等待设备端 Toast 事件回调推送，超时抛 `DevhelmTimeoutError`。需先调用 `start_listen_toast`。

#### `check_toast(text, fuzzy="equal", timeout=3.0) -> bool`

检查 Toast 是否包含指定文本。

| 参数 | 说明 |
|------|------|
| text | 期望文本 |
| fuzzy | `"equal"` / `"contains"` / `"startswith"` |
| timeout | 等待超时（秒） |

```python
d.start_listen_toast()
d(text="提交").click()
if d.check_toast("保存成功", fuzzy="contains"):
    print("操作成功")
```

#### `start_listen_ui_event(event_type: str) -> None`

开始 UI 事件监听（once 模式）。

| event_type | 说明 |
|------------|------|
| `"dialogShow"` | 对话框显示 |
| `"windowChange"` | 窗口变化 |
| `"componentEventOccur"` | 组件事件 |

#### `get_latest_ui_event(timeout: float = 3.0) -> Optional[dict]`

获取最新 UI 事件数据。阻塞等待设备端事件回调推送，超时返回 `None`。需先调用 `start_listen_ui_event`。

---

### WebView

> 需要安装可选依赖：`pip install devhelmkit[webview]`

#### `webview(bundle_name, chromedriver_search_path="", chromedriver_exe_path="", remote_devtools_port=None, connection_timeout=60, options=None) -> WebViewDriver`

通过 chromedriver + selenium 连接应用 WebView。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| bundle_name | str | — | 目标应用包名 |
| chromedriver_search_path | str | "" | chromedriver 存放目录（多版本结构） |
| chromedriver_exe_path | str | "" | 直接指定 chromedriver 路径（优先于 search_path） |
| remote_devtools_port | int | None | 自定义 WebView 内核 devtools 端口；系统 web 内核无需指定 |
| connection_timeout | int | 60 | 连接超时（秒） |
| options | - | None | 传递给 selenium webdriver 的 options |

```python
wv = d.webview(
    "com.huawei.hmos.browser",
    chromedriver_search_path="/path/to/chromedriver_search_path"
)

wv.driver.get("https://www.example.com")
wv.driver.find_element("id", "search").send_keys("devhelmkit")

wv.close()
```

---

## 数据类型

### Rect

```python
from devhelmkit.model.rect import Rect
```

| 字段/属性 | 类型 | 说明 |
|-----------|------|------|
| left | int | 左边界 |
| top | int | 上边界 |
| right | int | 右边界 |
| bottom | int | 下边界 |
| width | int | 宽度（属性） |
| height | int | 高度（属性） |
| center | Point | 中心点（属性） |
| top_left | Point | 左上角（属性） |
| bottom_right | Point | 右下角（属性） |

#### `contains(point: Point) -> bool`

判断点是否在矩形内。

#### `as_tuple() -> Tuple[int, int, int, int]`

返回 `(left, top, right, bottom)`。

---

### Point

| 字段 | 类型 | 说明 |
|------|------|------|
| x | int | X 坐标 |
| y | int | Y 坐标 |

#### `as_tuple() -> Tuple[int, int]`

返回 `(x, y)`。

---

### BaseWindow

```python
from devhelmkit.core.base_window import BaseWindow
```

窗口对象契约，通过 `d.window` 或 `d.get_windows()` 获取。

| 属性/方法 | 类型 | 说明 |
|-----------|------|------|
| size | Tuple[int, int] | 窗口大小 `(width, height)`（属性） |
| info | Dict[str, Any] | 窗口信息（属性） |
| get_windows() | List[BaseWindow] | 获取所有窗口 |

> 当前 HarmonyOS 实现中，`size` 回退为屏幕尺寸，`info` 返回空字典，`get_windows()` 返回空列表。

---

### GestureAction

```python
from devhelmkit.model.input import GestureAction, InputDevice

g = GestureAction(input_device=InputDevice.TOUCH)
g.add_step("move", 100, 200)
g.add_step("move", 200, 300)
d.inject_gesture(g, speed=1000)
```

| 字段 | 类型 | 说明 |
|------|------|------|
| steps | List[GestureStep] | 手势步骤列表 |
| input_device | InputDevice | 输入设备类型 |

#### `add_step(action, x, y, duration=0.0)`

添加手势步骤。`action` 为 `"move"` / `"down"` / `"up"`。

---

### InputDevice

| 成员 | 值 | 说明 |
|------|----|------|
| TOUCH | 0 | 触摸 |
| MOUSE | 1 | 鼠标 |
| PEN | 2 | 触控笔 |
| KNUCKLE | 3 | 指关节 |
| TOUCHPAD | 4 | 触控板 |

---

### MouseButton

| 成员 | 值 | 说明 |
|------|----|------|
| LEFT | 0 | 左键 |
| RIGHT | 1 | 右键 |
| MIDDLE | 2 | 中键 |

---

### KeyCode

OpenHarmony 按键码体系（非 Android KeyEvent）。

```python
from devhelmkit.model.keys import KeyCode

d.press_keycode(KeyCode.BACK)     # 返回键
d.press_keycode(KeyCode.HOME)     # Home 键
d.press_keycode(KeyCode.ENTER)    # 确认键
```

常用成员：`HOME`、`BACK`、`POWER`、`ENTER`、`VOLUME_UP`、`VOLUME_DOWN`、`VOLUME_MUTE`、`CAMERA`、`DPAD_UP`、`DPAD_DOWN`、`DPAD_LEFT`、`DPAD_RIGHT`、`DPAD_CENTER`、`PAGE_UP`、`PAGE_DOWN`、`MOVE_HOME`、`MOVE_END`、`MEDIA_PLAY_PAUSE`、`MEDIA_NEXT`、`MEDIA_PREVIOUS`、`BRIGHTNESS_UP`、`BRIGHTNESS_DOWN`、`SLEEP`、`WAKE_UP`、`SCREENLOCK`。

---

### OcrResult

```python
from devhelmkit.model.ocr_result import OcrResult
```

| 字段 | 类型 | 说明 |
|------|------|------|
| text | str | 识别出的文本 |
| bounds | Rect | 文本坐标矩形 |
| confidence | float | 置信度（0–1），越高越可信 |
| center | Point | 文本中心点（属性） |

---

### SelectorSpec

```python
from devhelmkit.core.selector_spec import build_selector

spec = build_selector(text="登录", className="Button")
d.find_component(spec)
```

纯数据类，封装控件定位条件。通常通过 `d(text="...", id="...")` 隐式构造。

支持字段：`text`、`text_contains`、`text_starts_with`、`text_ends_with`、`text_matches`、`desc`、`desc_contains`、`desc_starts_with`、`desc_ends_with`、`desc_matches`、`resource_id` / `id`、`class_name` / `className`、`key`、`type`、`instance`、`xpath`。`index` 与 `text_matches_flags` 不受支持，传入抛 `DevhelmError`。

---

### HarmonyDriverConfig

```python
from devhelmkit.harmony.config import HarmonyDriverConfig

config = HarmonyDriverConfig(
    implicit_wait=10.0,
    screenshot_mode="hdc",
    stop_daemon_on_close=False,
)
d = devhelmkit.connect(config=config)
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| implicit_wait | float | 10.0 | 控件查找默认超时（秒），非零以容忍异步渲染；可 `connect(implicit_wait=...)` 设置或运行时 `implicitly_wait()` 覆盖 |
| pop_window_dismiss | str | `"disable"` | 弹窗自动消除：`"enable"` / `"disable"` |
| pop_window_retry_find_timeout | int | 2 | 弹窗消除后重试查找超时（秒），仅 `pop_window_dismiss="enable"` 生效 |
| wait_time_after_pop_window_dismiss | int | 1 | 弹窗消除后、重试查找前的等待秒数 |
| pop_window_handle_times | int | 4 | 单次查找失败时最多尝试消除的弹窗个数 |
| clear_text_mode | str | `"once"` | `"once"`（`clearText`）或 `"select_all"`（全选+删，兜底 clearText 不生效） |
| clear_text_before_input | bool | True | `set_text` 前是否先清空（默认替换语义）|
| screenshot_mode | str | `"hdc"` | `"hdc"`（默认）或 `"stream"`（低延迟） |
| screenshot_stream_scale | float | 0.99 | 流截图缩放比例 |
| screenshot_retry_times | int | 3 | HDC 截图失败重试次数 |
| stop_daemon_on_close | bool | False | `close()` 时是否停止 uitest 守护进程 |
| restart_daemon_on_setup | bool | False | setup 时是否先清理残留 uitest 守护进程再重启（绕过复用优先） |
| hdc_path | str | `"hdc"` | hdc 可执行文件路径 |

---

## 异常体系

所有异常继承自 `DevhelmError`。

```
DevhelmError
├── DeviceNotFoundError          # 未检测到可连接设备
├── DeviceConnectError          # 设备连接失败
├── PlatformNotSupportedError   # 平台不支持
├── DevhelmTimeoutError         # 操作超时
├── RpcError                    # RPC 调用失败
│   └── BackendObjectDroppedError  # 远程对象引用已失效
├── ComponentNotFoundError      # 控件未找到
│   └── ComponentDisappearedError  # 控件查找到后又消失
└── AgentError                  # 设备端 Agent 异常
```

```python
from devhelmkit import ComponentNotFoundError

try:
    d(text="不存在的控件").click(timeout=5)
except ComponentNotFoundError:
    print("控件未找到")
```

---

## 许可证

[Apache License 2.0](LICENSE)