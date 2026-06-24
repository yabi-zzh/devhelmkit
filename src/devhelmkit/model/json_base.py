# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""JsonBase：JSON 序列化基类。

过滤 None 值、支持 api_level 参数、不使用 @dataclass，确保 RPC 协议兼容性。
"""
import json
from typing import Any, Dict


class JsonBase:
    """JSON 序列化基类。"""

    def to_dict(self, api_level: int = 9) -> Dict[str, Any]:
        """转换为字典（过滤 None 值）。

        Args:
            api_level: API 版本级别，用于版本兼容。
        """
        result = {}
        for key, value in self.__dict__.items():
            if value is not None:
                result[key] = value
        return result

    def to_json(self) -> str:
        """转换为 JSON 字符串。"""
        return json.dumps(self.to_dict(), ensure_ascii=False,
                          separators=(',', ':'))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        """从字典创建实例。"""
        obj = cls.__new__(cls)
        for key, value in data.items():
            setattr(obj, key, value)
        return obj

    @classmethod
    def from_json(cls, json_str: str):
        """从 JSON 字符串创建实例。"""
        return cls.from_dict(json.loads(json_str))
