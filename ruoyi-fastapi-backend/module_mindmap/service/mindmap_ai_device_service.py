"""Revocable companion enrollment and cross-worker discovery leases.

Every connection/message rechecks durable credentials. A reconnect replaces
only a disconnected/expired lease; stale cleanup cannot mark its successor offline.
No provider credential, path, prompt, shell command or document crosses here.
"""

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from module_admin.entity.do.user_do import SysUser
from module_mindmap.ai.runtime_catalog import RUNTIME_DEFINITIONS
from module_mindmap.ai.runtime_trace import public_text
from module_mindmap.entity.do.mindmap_ai_device_do import MindmapAiDevice
from module_mindmap.entity.vo.mindmap_ai_device_vo import DeviceEnrollment, DeviceFrame

PAIRING_TTL_SECONDS = 300
CREDENTIAL_TTL_DAYS = 90
ONLINE_TTL_SECONDS = 20
MAX_ACTIVE_DEVICES = 8
MAX_SCAN_REVISION = 2_147_483_647
SECRET_LENGTH = 43


def secret_digest(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def device_view(device: MindmapAiDevice, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now()
    status = device.status
    if status == 'pending' and device.pairing_expires_time <= now:
        status = 'pairing_expired'
    elif status == 'active' and device.credential_expires_time <= now:
        status = 'credential_expired'
    elif status == 'active':
        status = 'online' if (
            device.connection_id and device.last_seen_time
            and device.last_seen_time > now - timedelta(seconds=ONLINE_TTL_SECONDS)
        ) else 'offline'
    return {
        'deviceId': device.id, 'name': device.name, 'status': status,
        'executionAvailable': False, 'capabilities': ['discover'],
        'lastSeenAt': device.last_seen_time.isoformat() if device.last_seen_time else None,
        'lastScanAt': device.last_scan_time.isoformat() if device.last_scan_time else None,
        'scanPending': device.scan_requested > device.scan_completed,
        'runtimes': json.loads(device.runtimes_json or '[]'),
    }


class MindmapAiDeviceService:
    @staticmethod
    async def create_pairing(db: AsyncSession, user_id: int, name: str) -> dict[str, Any]:
        # Serialize device-limit checks for this owner across all server workers.
        owner = (await db.execute(select(SysUser.user_id).where(
            SysUser.user_id == user_id, SysUser.status == '0', SysUser.del_flag == '0',
        ).with_for_update())).scalar_one_or_none()
        if owner is None:
            raise HTTPException(403, '当前账号不可配对设备')
        now = datetime.now()
        count = (await db.execute(select(func.count()).select_from(MindmapAiDevice).where(
            MindmapAiDevice.user_id == user_id,
            ((MindmapAiDevice.status == 'active') & (MindmapAiDevice.credential_expires_time > now))
            | ((MindmapAiDevice.status == 'pending') & (MindmapAiDevice.pairing_expires_time > now)),
        ))).scalar_one()
        if count >= MAX_ACTIVE_DEVICES:
            raise HTTPException(409, '最多配对 8 台设备，请先撤销不再使用的设备')
        secret = secrets.token_urlsafe(32)
        device = MindmapAiDevice(
            id=str(uuid4()), user_id=user_id, name=public_text(name, 80).strip() or '我的电脑', status='pending',
            pairing_hash=secret_digest(secret), pairing_expires_time=now + timedelta(seconds=PAIRING_TTL_SECONDS),
            credential_expires_time=now + timedelta(days=CREDENTIAL_TTL_DAYS),
            scan_requested=1, scan_completed=0, created_time=now,
        )
        db.add(device)
        await db.commit()
        return {'deviceId': device.id, 'pairingCode': f'{device.id}.{secret}', 'expiresIn': PAIRING_TTL_SECONDS}

    @staticmethod
    async def enroll(db: AsyncSession, enrollment: DeviceEnrollment) -> dict[str, Any]:
        device = (await db.execute(select(MindmapAiDevice).join(
            SysUser, SysUser.user_id == MindmapAiDevice.user_id,
        ).where(
            MindmapAiDevice.id == enrollment.device_id, SysUser.status == '0', SysUser.del_flag == '0',
        ).with_for_update())).scalar_one_or_none()
        secret = enrollment.pairing_secret.get_secret_value()
        credential = enrollment.device_secret.get_secret_value()
        now = datetime.now()
        if (
            device is None or device.status not in {'pending', 'active'}
            or device.pairing_expires_time <= now
            or not hmac.compare_digest(device.pairing_hash or '', secret_digest(secret))
        ):
            raise HTTPException(401, '配对码无效、已使用或已过期')
        digest = secret_digest(credential)
        if device.status == 'active' and not hmac.compare_digest(device.credential_hash or '', digest):
            raise HTTPException(401, '配对码无效、已使用或已过期')
        # Client persisted its key before enrollment. A lost HTTP response may
        # retry only that exact key within the original pairing window.
        device.credential_hash = digest
        device.status = 'active'
        await db.commit()
        return {'deviceId': device.id, 'protocolVersion': 1, 'capabilities': ['discover']}

    @staticmethod
    async def list_devices(db: AsyncSession, user_id: int) -> list[dict[str, Any]]:
        now = datetime.now()
        # Old expired pairing attempts must never push usable devices outside
        # the bounded list and make it impossible for their owner to revoke.
        usable = (
            ((MindmapAiDevice.status == 'active') & (MindmapAiDevice.credential_expires_time > now))
            | ((MindmapAiDevice.status == 'pending') & (MindmapAiDevice.pairing_expires_time > now))
        )
        records = (await db.execute(select(MindmapAiDevice).where(
            MindmapAiDevice.user_id == user_id,
        ).order_by(usable.desc(), MindmapAiDevice.created_time.desc()).limit(50))).scalars().all()
        return [device_view(record) for record in records]

    @staticmethod
    async def revoke(db: AsyncSession, user_id: int, device_id: str) -> None:
        result = await db.execute(update(MindmapAiDevice).where(
            MindmapAiDevice.id == device_id, MindmapAiDevice.user_id == user_id,
        ).values(status='revoked', pairing_hash=None, credential_hash=None, connection_id=None,
                 revoked_time=datetime.now()))
        if not result.rowcount:
            raise HTTPException(404, '设备不存在')
        await db.commit()

    @staticmethod
    async def request_scan(db: AsyncSession, user_id: int, device_id: str) -> None:
        # Coalesce repeated clicks; there is never an unbounded command queue.
        device = (await db.execute(select(MindmapAiDevice).where(
            MindmapAiDevice.id == device_id, MindmapAiDevice.user_id == user_id,
        ).with_for_update())).scalar_one_or_none()
        if device is None:
            raise HTTPException(404, '设备不存在')
        if device_view(device)['status'] != 'online':
            raise HTTPException(409, '设备未在线，请先启动本地桥接')
        if device.scan_requested == device.scan_completed:
            if device.scan_requested >= MAX_SCAN_REVISION:
                raise HTTPException(409, '设备扫描序号已耗尽，请重新配对')
            device.scan_requested += 1
        await db.commit()

    @staticmethod
    async def authenticate(db: AsyncSession, device_id: str, credential: str) -> MindmapAiDevice:
        if len(credential) != SECRET_LENGTH:
            raise HTTPException(401, '设备认证失败')
        device = (await db.execute(select(MindmapAiDevice).join(
            SysUser, SysUser.user_id == MindmapAiDevice.user_id,
        ).where(
            MindmapAiDevice.id == device_id, MindmapAiDevice.status == 'active',
            MindmapAiDevice.credential_expires_time > datetime.now(),
            SysUser.status == '0', SysUser.del_flag == '0',
        ).with_for_update())).scalar_one_or_none()
        if device is None or not hmac.compare_digest(device.credential_hash or '', secret_digest(credential)):
            raise HTTPException(401, '设备认证失败')
        return device

    @classmethod
    async def connect(cls, db: AsyncSession, device_id: str, credential: str) -> str:
        device = await cls.authenticate(db, device_id, credential)
        now = datetime.now()
        # authenticate holds the device row lock across this check and commit.
        # Replacing a live discovery socket also cancels its paired execution
        # client, even when the newcomer is rejected by the execution slot.
        if (device.connection_id and device.last_seen_time
                and device.last_seen_time > now - timedelta(seconds=ONLINE_TTL_SECONDS)):
            raise HTTPException(409, '设备已有在线桥接，请先停止原实例后重试',
                                headers={'Retry-After': str(ONLINE_TTL_SECONDS)})
        if device.scan_requested == device.scan_completed:
            if device.scan_requested >= MAX_SCAN_REVISION:
                raise HTTPException(409, '设备扫描序号已耗尽，请重新配对')
            device.scan_requested += 1
        connection_id = str(uuid4())
        device.connection_id = connection_id
        device.last_seen_time = now
        await db.commit()
        return connection_id

    @classmethod
    async def receive(
        cls, db: AsyncSession, device_id: str, credential: str, connection_id: str, frame: DeviceFrame,
    ) -> dict[str, Any]:
        device = await cls.authenticate(db, device_id, credential)
        if device.connection_id != connection_id:
            raise HTTPException(409, '设备已有新的连接')
        now = datetime.now()
        if frame.type == 'scan_result':
            keys = [item.agent_key for item in frame.runtimes]
            if len(set(keys)) != len(keys) or set(keys) != {item.key for item in RUNTIME_DEFINITIONS}:
                raise HTTPException(400, '扫描结果必须包含全部已知 Agent，且不能重复')
            if frame.scan_revision > device.scan_requested:
                raise HTTPException(400, '扫描序号无效')
            if frame.scan_revision == device.scan_requested and frame.scan_revision > device.scan_completed:
                definitions = {item.key: item for item in RUNTIME_DEFINITIONS}
                runtimes = []
                for item in frame.runtimes:
                    if item.installed == (item.status == 'not_installed'):
                        raise HTTPException(400, '扫描安装状态不一致')
                    definition = definitions[item.agent_key]
                    runtimes.append({**item.model_dump(by_alias=True), 'displayName': definition.name, 'protocol': definition.protocol,
                                     'location': 'user_device', 'authenticationStatus': 'unknown', 'executionAvailable': False})
                device.runtimes_json = json.dumps(runtimes, ensure_ascii=False)
                device.scan_completed = frame.scan_revision
                device.last_scan_time = now
        elif frame.runtimes:
            raise HTTPException(400, '心跳不能携带扫描结果')
        device.last_seen_time = now
        response = {'type': 'state', 'protocolVersion': 1, 'scanRevision': device.scan_requested,
                    'executionAvailable': False, 'capabilities': ['discover']}
        await db.commit()
        return response

    @staticmethod
    async def disconnect(db: AsyncSession, device_id: str, connection_id: str) -> None:
        await db.execute(update(MindmapAiDevice).where(
            MindmapAiDevice.id == device_id, MindmapAiDevice.connection_id == connection_id,
        ).values(connection_id=None))
        await db.commit()
