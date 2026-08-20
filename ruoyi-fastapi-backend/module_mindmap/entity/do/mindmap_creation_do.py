from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, String

from config.database import Base


class MindmapCreationRequest(Base):
    """Durable idempotency record for irreversible mindmap creation requests."""

    __tablename__ = 'mindmap_creation_request'
    __table_args__ = (
        Index(
            'uk_mindmap_creation_owner_request',
            'owner_id',
            'request_id',
            unique=True,
        ),
        Index('idx_mindmap_creation_result', 'result_file_id'),
        Index('idx_mindmap_creation_created', 'created_time'),
        Index('idx_mindmap_creation_retention', 'completed_time', 'id'),
        {'comment': '脑图创建请求幂等记录'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    owner_id = Column(BigInteger, nullable=False)
    request_id = Column(String(100), nullable=False, comment='客户端创建请求幂等键')
    operation = Column(String(32), nullable=False, comment='blank/template/copy/import')
    request_fingerprint = Column(String(64), nullable=False, comment='规范化创建意图SHA-256')
    result_file_id = Column(BigInteger, nullable=True, comment='成功创建的脑图文件ID')
    created_by = Column(String(64), nullable=True)
    created_time = Column(DateTime, nullable=False, default=datetime.now)
    completed_time = Column(DateTime, nullable=True)
