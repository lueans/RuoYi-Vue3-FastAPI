-- File: ruoyi-fastapi-backend/migrations/mindmap_tables.sql

CREATE TABLE `mindmap` (
    `id`              BIGINT       NOT NULL AUTO_INCREMENT COMMENT '思维导图ID',
    `name`            VARCHAR(200) NOT NULL COMMENT '思维导图名称',
    `description`     VARCHAR(500) DEFAULT NULL COMMENT '描述',
    `owner_id`        BIGINT       NOT NULL COMMENT '所有者用户ID',
    `layout`          VARCHAR(50)  NOT NULL DEFAULT 'logicalStructure' COMMENT '布局类型',
    `theme`           JSON         DEFAULT NULL COMMENT '主题配置JSON',
    `node_tree`       LONGTEXT     NOT NULL COMMENT '完整节点树JSON',
    `view_data`       JSON         DEFAULT NULL COMMENT '视图状态JSON',
    `cover_image`     VARCHAR(500) DEFAULT NULL COMMENT '封面图片URL',
    `is_template`     SMALLINT     NOT NULL DEFAULT 0 COMMENT '是否模板（0否 1是）',
    `last_version_id` BIGINT       DEFAULT NULL COMMENT '最新版本ID',
    `version_count`   INT          NOT NULL DEFAULT 1 COMMENT '版本总数',
    `status`          SMALLINT     NOT NULL DEFAULT 0 COMMENT '状态（0正常 1归档）',
    `del_flag`        CHAR(1)      NOT NULL DEFAULT '0' COMMENT '删除标志（0存在 2删除）',
    `create_by`       VARCHAR(64)  DEFAULT '' COMMENT '创建者',
    `create_time`     DATETIME     DEFAULT NULL COMMENT '创建时间',
    `update_by`       VARCHAR(64)  DEFAULT '' COMMENT '更新者',
    `update_time`     DATETIME     DEFAULT NULL COMMENT '更新时间',
    `remark`          VARCHAR(500) DEFAULT NULL COMMENT '备注',
    PRIMARY KEY (`id`),
    INDEX `idx_mindmap_owner` (`owner_id`, `del_flag`),
    INDEX `idx_mindmap_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='思维导图主表';
