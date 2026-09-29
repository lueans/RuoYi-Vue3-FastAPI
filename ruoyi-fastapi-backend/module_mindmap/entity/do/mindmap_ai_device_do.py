"""User-owned companion credentials. Raw pairing/device secrets are never stored."""

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String, Text

from config.database import Base


class MindmapAiDevice(Base):
    __tablename__ = 'mindmap_ai_device'
    __table_args__ = (Index('idx_mindmap_ai_device_owner', 'user_id', 'created_time'),)

    id = Column(String(36), primary_key=True)
    user_id = Column(BigInteger, nullable=False)
    name = Column(String(80), nullable=False)
    status = Column(String(16), nullable=False)
    pairing_hash = Column(String(64), nullable=True)
    pairing_expires_time = Column(DateTime, nullable=False)
    credential_hash = Column(String(64), nullable=True)
    credential_expires_time = Column(DateTime, nullable=False)
    connection_id = Column(String(36), nullable=True)
    scan_requested = Column(Integer, nullable=False, default=1)
    scan_completed = Column(Integer, nullable=False, default=0)
    runtimes_json = Column(Text, nullable=True)
    last_seen_time = Column(DateTime, nullable=True)
    last_scan_time = Column(DateTime, nullable=True)
    created_time = Column(DateTime, nullable=False)
    revoked_time = Column(DateTime, nullable=True)
