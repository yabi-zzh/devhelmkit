# 更新日志

本项目所有值得注意的变更均记录于此文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.5.0]

### 新增

- 控件选择器新增集合 API：通过 `count` 获取匹配数量，通过 `all()`、`first()`、`last()` 获取全部、首个或末个匹配控件。
- 控件新增条件等待 API：`wait_enabled()`、`wait_disabled()`、`wait_clickable()`，以及接收控件信息断言的 `wait_until()`。
- Driver 目标参数支持直接传入 `UiObject`，可复用控件选择器执行边界查询、拖拽等操作。

### 变更

- `click_exists()` 更名为 `click_if_exists()`；旧名称不再保留。迁移时请直接替换方法名，参数和布尔返回语义保持一致。

### 修复

- HarmonyOS `set_text()` 改用设备端 `Component.inputText` API，修复部分输入框无法写入文本的问题。
- XPath 批量查找返回全部匹配控件，不再退化为单控件结果。

## [0.4.1]

### 性能

- 纯类型 XPath（如 `//Text`）可直接下推至设备端选择器，绕过控件树解析与 bounds 锚定，降低常见类型查询延迟。
- 批量 XPath 按控件类型分组并复用候选扫描，减少重复 RPC 与 bounds 查询。

### 修复

- XPath 单控件查找在 `timeout` 内轮询控件树，支持异步渲染以及节点出现后的 bounds 锚定竞态。
- 非法 XPath 在轮询前快速失败；设备端快速路径失败时保留用户传入的原始 XPath 上下文。

## [0.4.0]

### 新增

- HarmonyOS XPath 改用 `lxml` 标准 XPath 1.0 引擎，支持谓词、位置和组合表达式；查询命中的节点可通过 `bounds` 精确锚定回设备端控件并继续执行点击、输入、属性读取等操作。
- UI Viewer 新增控件 XPath 候选生成与切换，可按控件类型、ID、文本等语义生成定位表达式。
- UI Viewer 新增操作录制，可记录点击、长按、输入、滑动和按键操作，生成可复制的 Python 自动化脚本，并支持删除或清空录制步骤。

### 变更

- UI Viewer 实时截图流、控件树模型和前端交互完成升级：统一顶层属性式与 `attributes` 包裹式控件树，增强画面缩放、选区和节点联动。
- XPath 与 UI Viewer 共享控件属性归一化边界，减少不同控件树来源之间的结构差异。
- UI Viewer 改用系统字体栈，不再依赖第三方字体 CDN，保持离线可用。

### 性能

- 优化录制定位器生成：优先返回不可超越的唯一 ID 或高质量语义候选，避免无效 XPath 与相对定位计算。
- 滑动录制直接按坐标生成脚本，不再解析控件树或统计选择器唯一性。

### 修复

- 修复实时截图流异常断开时等待消费者不能立即被唤醒的问题。
- 收紧 UI Viewer JSON 请求边界：处理非法 `Content-Length`，限制请求体大小，并拒绝非对象 JSON。
- 修复属性式控件树的 `children` 子树被复制进扁平节点属性，导致响应体随树深度放大的问题。

## [0.3.2]

### 新增

- HarmonyOS 新增配置项 `restart_daemon_on_setup`（默认 `False`）：setup 时先清理设备端残留 uitest 守护进程再重启，绕过复用优先策略，规避残留 daemon 版本不匹配或状态损坏导致的连接异常。

### 变更

- HarmonyOS uitest 守护进程探测与清理弃用设备端 `pgrep -fl`，改为 `ps -ef` 拉原始输出、host 侧 Python 过滤 pid，规避 toybox `pgrep -f` 匹配不完整或输出格式不一致的问题；探测与清理复用同一套匹配逻辑。

### 修复

- 优化 OCR 模糊文本匹配：`fuzzy=True` 先对文本做归一化（NFKC 兼容分解、去空白与零宽字符、casefold 忽略大小写）后子串匹配，再以 `SequenceMatcher` 相似度兜底，提升识别文本的匹配鲁棒性。

## [0.3.1]

### 修复

- 修复 HarmonyOS 应用启动入口解析：主 Ability 改为读取 `mainAbility` 的第一个非空值，`module` 仅在显式传入时拼接 `-m`。

## [0.3.0]

### 新增

- HarmonyOS UI 自动化：选择器链、控件操作、设备控制、应用管理。
- 高级手势：鼠标、触控笔（带压力）、指关节、触控板、多指。
- WebView 自动化（chromedriver + selenium）。
- 图像匹配（OpenCV 模板 + 特征匹配）与 OCR（RapidOCR）。
- 双查找后端：uitest（设备端 RPC）+ uitree（本地布局解析）。
- 屏幕录制：JPEG 帧捕获与 MP4 编码。
- 网页版 UIViewer：本地双端口 Web 服务，实时投屏查看控件，支持画面刷新、设备导航键、触控与性能日志。
- PEP 561 类型标记（`py.typed`），下游可识别类型注解。
- 开源社区文件：贡献指南、行为准则、安全政策、Issue/PR 模板。

### 变更

- 采用 src layout 目录结构（包源码位于 `src/devhelmkit/`）。
- `license` 声明改用 SPDX 表达式格式。

[0.5.0]: https://github.com/yabi-zzh/devhelmkit/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/yabi-zzh/devhelmkit/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/yabi-zzh/devhelmkit/compare/v0.3.2...v0.4.0
[0.3.2]: https://github.com/yabi-zzh/devhelmkit/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/yabi-zzh/devhelmkit/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/yabi-zzh/devhelmkit/releases/tag/v0.3.0
