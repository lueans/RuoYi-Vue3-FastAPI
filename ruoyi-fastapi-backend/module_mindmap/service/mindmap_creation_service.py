import json
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from common.vo import CrudResponseModel
from exceptions.exception import ServiceException
from module_mindmap.entity.do.mindmap_creation_do import MindmapCreationRequest

MIN_CREATION_REQUEST_ID_LENGTH = 16
MAX_CREATION_REQUEST_ID_LENGTH = 100
MAX_CREATION_OPERATION_LENGTH = 32
CREATION_REQUEST_ID_PATTERN = r'^[A-Za-z0-9][A-Za-z0-9._:-]*$'
_CREATION_REQUEST_ID_RE = re.compile(CREATION_REQUEST_ID_PATTERN)


@dataclass(frozen=True)
class MindmapCreationContext:
    request_id: str
    operation: str
    request_fingerprint: str


class MindmapCreationService:
    """Pure creation-idempotency rules shared by every creation workflow."""

    @classmethod
    def build_context(
        cls,
        request_id: str,
        operation: str,
        intent: dict[str, Any],
    ) -> MindmapCreationContext:
        normalized_request_id = cls.normalize_request_id(request_id)
        normalized_operation = operation.strip().lower()
        if not normalized_operation or len(normalized_operation) > MAX_CREATION_OPERATION_LENGTH:
            raise ServiceException(message='脑图创建操作类型无效')
        try:
            canonical = json.dumps(
                {'operation': normalized_operation, 'intent': intent},
                ensure_ascii=False,
                sort_keys=True,
                separators=(',', ':'),
                allow_nan=False,
            ).encode()
        except (TypeError, ValueError) as exc:
            raise ServiceException(message='脑图创建请求内容无效') from exc
        return MindmapCreationContext(
            request_id=normalized_request_id,
            operation=normalized_operation,
            request_fingerprint=sha256(canonical).hexdigest(),
        )

    @staticmethod
    def normalize_request_id(request_id: str) -> str:
        value = request_id.strip() if isinstance(request_id, str) else ''
        if not (
            MIN_CREATION_REQUEST_ID_LENGTH <= len(value) <= MAX_CREATION_REQUEST_ID_LENGTH
            and _CREATION_REQUEST_ID_RE.fullmatch(value)
        ):
            raise ServiceException(message='Idempotency-Key 格式无效')
        return value

    @staticmethod
    def resolve_replay(
        record: MindmapCreationRequest,
        context: MindmapCreationContext,
    ) -> CrudResponseModel:
        if (
            record.operation != context.operation
            or record.request_fingerprint != context.request_fingerprint
        ):
            raise ServiceException(message='Idempotency-Key 已用于不同的脑图创建请求')
        if not record.result_file_id:
            # A record and its result are committed atomically. Seeing an
            # incomplete committed row therefore signals corrupted state.
            raise ServiceException(message='脑图创建幂等记录不完整，请联系管理员')
        return CrudResponseModel(
            is_success=True,
            message='新增成功',
            result={'id': record.result_file_id, 'idempotentReplay': True},
        )
