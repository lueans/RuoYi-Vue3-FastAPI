"""A small, closed discovery protocol, deliberately not a command-execution API."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints
from pydantic.alias_generators import to_camel

DeviceId = Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$')]


class DevicePairRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)


class _DeviceInput(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True, alias_generator=to_camel)


class DeviceEnrollment(_DeviceInput):
    device_id: DeviceId
    pairing_secret: SecretStr = Field(min_length=43, max_length=43)
    device_secret: SecretStr = Field(min_length=43, max_length=43)


class DeviceRuntimeReport(_DeviceInput):
    agent_key: Literal['claude', 'codex', 'kimi']
    installed: bool = Field(strict=True)
    version: str | None = Field(default=None, max_length=80, pattern=r'^\d+\.\d+(?:\.\d+)?(?:[-+][\w.]+)?$')
    status: Literal['not_installed', 'detected', 'incompatible', 'probe_failed']
    capabilities: list[Literal['partial_messages', 'session_mirror', 'resume', 'acp']] = Field(default_factory=list, max_length=4)


class DeviceFrame(_DeviceInput):
    type: Literal['heartbeat', 'scan_result']
    protocol_version: int = Field(default=1, strict=True, ge=1, le=1)
    scan_revision: int = Field(default=0, strict=True, ge=0, le=2_147_483_647)
    runtimes: list[DeviceRuntimeReport] = Field(default_factory=list, max_length=3)
