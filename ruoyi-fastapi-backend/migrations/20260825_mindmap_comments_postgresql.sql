-- 脑图节点评论（PostgreSQL 14+，可重复执行）

BEGIN;

CREATE TABLE IF NOT EXISTS mindmap_comment_thread (
    id BIGSERIAL PRIMARY KEY,
    mindmap_id BIGINT NOT NULL,
    node_uid VARCHAR(64) NOT NULL,
    node_text VARCHAR(500),
    status SMALLINT NOT NULL DEFAULT 0,
    created_by BIGINT NOT NULL,
    created_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_comment_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_by BIGINT,
    resolved_time TIMESTAMP,
    del_flag CHAR(1) NOT NULL DEFAULT '0'
);

CREATE INDEX IF NOT EXISTS idx_mindmap_comment_thread_file
    ON mindmap_comment_thread (mindmap_id, status, last_comment_time);
CREATE INDEX IF NOT EXISTS idx_mindmap_comment_thread_node
    ON mindmap_comment_thread (mindmap_id, node_uid, status);

CREATE TABLE IF NOT EXISTS mindmap_comment (
    id BIGSERIAL PRIMARY KEY,
    thread_id BIGINT NOT NULL,
    mindmap_id BIGINT NOT NULL,
    content TEXT NOT NULL,
    created_by BIGINT NOT NULL,
    client_request_id VARCHAR(100),
    created_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP,
    del_flag CHAR(1) NOT NULL DEFAULT '0'
);

CREATE INDEX IF NOT EXISTS idx_mindmap_comment_thread
    ON mindmap_comment (thread_id, created_time);
CREATE INDEX IF NOT EXISTS idx_mindmap_comment_author
    ON mindmap_comment (created_by, created_time);
CREATE UNIQUE INDEX IF NOT EXISTS uk_mindmap_comment_author_request
    ON mindmap_comment (created_by, client_request_id);

COMMENT ON TABLE mindmap_comment_thread IS '脑图评论线程表';
COMMENT ON TABLE mindmap_comment IS '脑图评论消息表';

COMMIT;
