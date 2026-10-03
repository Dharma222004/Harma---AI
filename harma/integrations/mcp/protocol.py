"""
Harma MCP — JSON-RPC 2.0 Protocol & Model Serialization

Defines standard JSON-RPC 2.0 request/response structures and standard MCP method constants
per the Model Context Protocol specification.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional, Union

# Standard MCP protocol constants
MCP_PROTOCOL_VERSION = "2024-11-05"
CLIENT_NAME = "Harma"
CLIENT_VERSION = "0.8.0"

# Standard JSON-RPC 2.0 Error Codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


@dataclass
class JSONRPCError:
    code: int
    message: str
    data: Optional[Any] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            d["data"] = self.data
        return d


@dataclass
class JSONRPCRequest:
    id: Union[str, int]
    method: str
    params: Optional[dict[str, Any]] = None
    jsonrpc: str = "2.0"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"jsonrpc": self.jsonrpc, "id": self.id, "method": self.method}
        if self.params is not None:
            d["params"] = self.params
        return d

    def serialize(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class JSONRPCNotification:
    method: str
    params: Optional[dict[str, Any]] = None
    jsonrpc: str = "2.0"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"jsonrpc": self.jsonrpc, "method": self.method}
        if self.params is not None:
            d["params"] = self.params
        return d

    def serialize(self) -> str:
        return json.dumps(self.to_dict())


@dataclass
class JSONRPCResponse:
    id: Optional[Union[str, int]]
    result: Optional[Any] = None
    error: Optional[JSONRPCError] = None
    jsonrpc: str = "2.0"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"jsonrpc": self.jsonrpc, "id": self.id}
        if self.error is not None:
            d["error"] = self.error.to_dict()
        else:
            d["result"] = self.result
        return d

    def serialize(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JSONRPCResponse:
        err = None
        if "error" in data and data["error"]:
            e = data["error"]
            err = JSONRPCError(code=e.get("code", INTERNAL_ERROR), message=e.get("message", "Error"), data=e.get("data"))
        return cls(id=data.get("id"), result=data.get("result"), error=err)
