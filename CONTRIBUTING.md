# 贡献指南

感谢你有兴趣为 devhelmkit 做出贡献。本文档说明提交 Issue 与 Pull Request 的流程与规范。

## 提交 Issue

在提交前，请先搜索 [已有 Issue](https://github.com/yabi-zzh/devhelmkit/issues)，避免重复。

- **Bug 报告**：请使用「Bug 报告」模板，提供可复现步骤、期望行为、实际行为，以及环境信息（操作系统、Python 版本、HarmonyOS 版本、设备型号、`hdc` 版本）。
- **功能请求**：请使用「功能请求」模板，说明需求场景与期望的 API 形态。
- **安全问题**：请勿公开提交，参见 [SECURITY.md](SECURITY.md)。

## 提交 Pull Request

1. Fork 仓库并从 `main` 创建特性分支（如 `feat/xxx`、`fix/xxx`）。
2. 完成修改并确保通过本地校验（见下文）。
3. 提交 PR，填写 PR 模板，关联相关 Issue。

### 代码分层约束

本项目遵循严格的分层，PR 需符合以下约束：

- `core/` 不得依赖任何平台实现，只定义跨平台契约。
- `model/` 无内部依赖，纯数据类型，可跨平台复用。
- 平台实现按 `device/`（设备通道）、`rpc/`（RPC 协议）、`finder/`（控件定位）组织。
- RPC 层不感知 UI 对象；设备通道不理解控件定位。
- 新增或修改公共 API 时，同步更新 [api_reference.md](api_reference.md)。

### 注释规范

- 注释只描述功能，不写外部项目引用，也不写开发过程信息。

### 本地校验

请将包安装为 editable 模式后进行修改：

```bash
pip install -e ".[dev]"
```

提交前请确保：

- 前端 JavaScript 用 `node --check` 校验语法。
- Python 用 `python -m compileall src` 编译校验，并用 `pyflakes` 检查未使用导入等静态问题。
- 若改动涉及可离线验证的逻辑，请附带相应的验证说明。

## 行为准则

参与本项目即表示你同意遵守 [行为准则](CODE_OF_CONDUCT.md)。

## 许可证

提交贡献即表示你同意其在 [Apache-2.0](LICENSE) 许可证下发布。