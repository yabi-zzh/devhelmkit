# 更新日志

本项目所有值得注意的变更均记录于此文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

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

[0.3.2]: https://github.com/yabi-zzh/devhelmkit/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/yabi-zzh/devhelmkit/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/yabi-zzh/devhelmkit/releases/tag/v0.3.0