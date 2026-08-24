"""脑图结构化内容模型。

这些表是 simple-mind-map 文档的持久化主数据。现有 mindmap.node_tree 在迁移期
继续作为兼容快照，不能作为新表的替代写入源。
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects import mysql, postgresql

from config.database import Base
from config.env import DataBaseConfig

JSON_TYPE = mysql.JSON if DataBaseConfig.db_type == 'mysql' else postgresql.JSONB
LONG_TEXT_TYPE = mysql.LONGTEXT if DataBaseConfig.db_type == 'mysql' else Text


class MindmapNode(Base):
    """脑图节点表。"""

    __tablename__ = 'mindmap_node'
    __table_args__ = (
        Index('uk_mindmap_node_uid', 'file_id', 'node_uid', unique=True),
        Index('idx_mindmap_node_parent', 'file_id', 'parent_id', 'sort_order'),
        Index('idx_mindmap_node_deleted', 'file_id', 'is_deleted'),
        {'comment': '脑图节点表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True, comment='节点ID')
    file_id = Column(BigInteger, nullable=False, comment='脑图文件ID')
    node_uid = Column(String(64), nullable=False, comment='simple-mind-map稳定UID')
    parent_id = Column(BigInteger, nullable=True, comment='父节点ID，根节点为空')
    sort_order = Column(Integer, nullable=False, server_default='0', comment='同级顺序')
    text_content = Column(LONG_TEXT_TYPE, nullable=True, comment='节点文本或富文本')
    text_plain = Column(Text, nullable=True, comment='用于搜索的纯文本')
    text_format = Column(String(16), nullable=False, server_default='plain', comment='plain/rich')
    is_expanded = Column(SmallInteger, nullable=False, server_default='1', comment='是否展开')
    direction = Column(String(16), nullable=True, comment='节点方向')
    custom_left = Column(Float, nullable=True, comment='自定义横坐标')
    custom_top = Column(Float, nullable=True, comment='自定义纵坐标')
    custom_text_width = Column(Float, nullable=True, comment='自定义文本宽度')
    content_data = Column(JSON_TYPE, nullable=True, comment='节点内容扩展JSON')
    style_data = Column(JSON_TYPE, nullable=True, comment='节点自定义样式JSON')
    extension_data = Column(JSON_TYPE, nullable=True, comment='未知/业务扩展字段JSON')
    envelope_data = Column(JSON_TYPE, nullable=True, comment='data/children同级扩展字段JSON')
    payload_schema_version = Column(Integer, nullable=False, server_default='1', comment='节点载荷版本')
    node_revision = Column(BigInteger, nullable=False, server_default='1', comment='节点修订号')
    is_deleted = Column(SmallInteger, nullable=False, server_default='0', comment='删除标记')
    deleted_time = Column(DateTime, nullable=True, comment='删除时间')
    create_by = Column(String(64), nullable=True, comment='创建者')
    create_time = Column(DateTime, nullable=True, default=datetime.now, comment='创建时间')
    update_by = Column(String(64), nullable=True, comment='更新者')
    update_time = Column(DateTime, nullable=True, default=datetime.now, onupdate=datetime.now, comment='更新时间')


class MindmapRelation(Base):
    """关联线等跨节点关系。"""

    __tablename__ = 'mindmap_relation'
    __table_args__ = (
        Index('uk_mindmap_relation_uid', 'file_id', 'relation_uid', unique=True),
        Index('idx_mindmap_relation_source', 'file_id', 'source_node_id', 'sort_order'),
        Index('idx_mindmap_relation_target', 'file_id', 'target_node_id'),
        {'comment': '脑图跨节点关系表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    relation_uid = Column(String(96), nullable=False, comment='稳定关系UID')
    file_id = Column(BigInteger, nullable=False)
    relation_type = Column(String(32), nullable=False, server_default='associative_line')
    source_node_id = Column(BigInteger, nullable=False)
    target_node_id = Column(BigInteger, nullable=False)
    text = Column(LONG_TEXT_TYPE, nullable=True)
    control_data = Column(JSON_TYPE, nullable=True)
    style_data = Column(JSON_TYPE, nullable=True)
    sort_order = Column(Integer, nullable=False, server_default='0')
    revision = Column(BigInteger, nullable=False, server_default='1')
    create_time = Column(DateTime, nullable=True, default=datetime.now)
    update_time = Column(DateTime, nullable=True, default=datetime.now, onupdate=datetime.now)


class MindmapSummary(Base):
    """节点概要（generalization）表。"""

    __tablename__ = 'mindmap_summary'
    __table_args__ = (
        Index('uk_mindmap_summary_uid', 'file_id', 'summary_uid', unique=True),
        Index('idx_mindmap_summary_owner', 'file_id', 'owner_node_id', 'sort_order'),
        {'comment': '脑图概要表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    summary_uid = Column(String(64), nullable=False)
    file_id = Column(BigInteger, nullable=False)
    owner_node_id = Column(BigInteger, nullable=False)
    start_child_id = Column(BigInteger, nullable=True)
    end_child_id = Column(BigInteger, nullable=True)
    content_data = Column(JSON_TYPE, nullable=True)
    style_data = Column(JSON_TYPE, nullable=True)
    extension_data = Column(JSON_TYPE, nullable=True)
    sort_order = Column(Integer, nullable=False, server_default='0')
    revision = Column(BigInteger, nullable=False, server_default='1')
    create_time = Column(DateTime, nullable=True, default=datetime.now)
    update_time = Column(DateTime, nullable=True, default=datetime.now, onupdate=datetime.now)


class MindmapGroup(Base):
    """外框等节点分组定义。"""

    __tablename__ = 'mindmap_group'
    __table_args__ = (
        Index('uk_mindmap_group_uid', 'file_id', 'group_uid', unique=True),
        Index('idx_mindmap_group_parent', 'file_id', 'parent_node_id'),
        {'comment': '脑图节点分组表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    group_uid = Column(String(64), nullable=False)
    file_id = Column(BigInteger, nullable=False)
    parent_node_id = Column(BigInteger, nullable=False)
    group_type = Column(String(32), nullable=False, server_default='outer_frame')
    text = Column(LONG_TEXT_TYPE, nullable=True)
    style_data = Column(JSON_TYPE, nullable=True)
    extension_data = Column(JSON_TYPE, nullable=True)
    revision = Column(BigInteger, nullable=False, server_default='1')
    create_time = Column(DateTime, nullable=True, default=datetime.now)
    update_time = Column(DateTime, nullable=True, default=datetime.now, onupdate=datetime.now)


class MindmapGroupMember(Base):
    """节点分组成员表。"""

    __tablename__ = 'mindmap_group_member'
    __table_args__ = (
        Index('uk_mindmap_group_member', 'group_id', 'node_id', unique=True),
        Index('idx_mindmap_group_member_order', 'group_id', 'sort_order'),
        {'comment': '脑图节点分组成员表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    group_id = Column(BigInteger, nullable=False)
    node_id = Column(BigInteger, nullable=False)
    sort_order = Column(Integer, nullable=False, server_default='0')


class MindmapAsset(Base):
    """脑图文件资源表。"""

    __tablename__ = 'mindmap_asset'
    __table_args__ = (
        Index('uk_mindmap_asset_key', 'file_id', 'asset_key', unique=True),
        Index('idx_mindmap_asset_hash', 'file_id', 'sha256'),
        {'comment': '脑图资源表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    file_id = Column(BigInteger, nullable=False)
    asset_key = Column(String(128), nullable=False)
    asset_type = Column(String(32), nullable=False, server_default='image')
    storage_type = Column(String(16), nullable=False, server_default='url')
    uri = Column(LONG_TEXT_TYPE, nullable=True)
    object_key = Column(String(500), nullable=True)
    mime_type = Column(String(100), nullable=True)
    size = Column(BigInteger, nullable=True)
    sha256 = Column(String(64), nullable=True)
    metadata_json = Column('metadata', JSON_TYPE, nullable=True)
    create_time = Column(DateTime, nullable=True, default=datetime.now)


class MindmapNodeTag(Base):
    """节点对标签主数据的引用关系。"""

    __tablename__ = 'mindmap_node_tag'
    __table_args__ = (
        Index('uk_mindmap_node_tag', 'node_id', 'tag_id', unique=True),
        Index('idx_mindmap_node_tag_usage', 'tag_id', 'file_id'),
        Index('idx_mindmap_node_tag_order', 'node_id', 'sort_order'),
        {'comment': '脑图节点标签关系表'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    file_id = Column(BigInteger, nullable=False)
    node_id = Column(BigInteger, nullable=False)
    tag_id = Column(BigInteger, nullable=False)
    sort_order = Column(Integer, nullable=False, server_default='0')
    placement = Column(String(16), nullable=True)
    align = Column(String(16), nullable=True)
    created_by = Column(String(64), nullable=True)
    created_time = Column(DateTime, nullable=True, default=datetime.now)


class MindmapChangeLog(Base):
    """文件级增量变更日志，同时承担 clientMutationId 幂等记录。"""

    __tablename__ = 'mindmap_change_log'
    __table_args__ = (
        Index('uk_mindmap_change_revision', 'file_id', 'revision', unique=True),
        Index('uk_mindmap_change_mutation', 'file_id', 'client_mutation_id', unique=True),
        Index('idx_mindmap_change_created', 'file_id', 'created_time'),
        Index('idx_mindmap_change_retention', 'created_time', 'id'),
        {'comment': '脑图增量变更与幂等日志'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    file_id = Column(BigInteger, nullable=False)
    base_revision = Column(BigInteger, nullable=False)
    revision = Column(BigInteger, nullable=False)
    client_mutation_id = Column(String(100), nullable=False)
    operations = Column(JSON_TYPE, nullable=False)
    result_data = Column(JSON_TYPE, nullable=True)
    created_by = Column(String(64), nullable=True)
    created_time = Column(DateTime, nullable=False, default=datetime.now)


class MindmapMigrationRecord(Base):
    """结构化迁移的文件级可审计结果。"""

    __tablename__ = 'mindmap_migration_record'
    __table_args__ = (
        Index('uk_mindmap_migration_file', 'file_id', unique=True),
        Index('idx_mindmap_migration_batch', 'batch_id', 'status'),
        {'comment': '脑图结构化迁移结果'},
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    file_id = Column(BigInteger, nullable=False)
    batch_id = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, comment='migrated/failed')
    legacy_hash = Column(String(64), nullable=True)
    structured_hash = Column(String(64), nullable=True)
    error_message = Column(String(2000), nullable=True)
    started_time = Column(DateTime, nullable=False)
    finished_time = Column(DateTime, nullable=False)
