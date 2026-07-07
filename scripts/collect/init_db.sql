-- PostgreSQL 메타데이터 테이블 초기화
-- 실행: psql -U mazel_user -d mazel_esthetic_db -h localhost -f scripts/init_db.sql

CREATE TABLE IF NOT EXISTS collection_log (
    id              SERIAL PRIMARY KEY,
    source          VARCHAR(50)  NOT NULL,
    started_at      TIMESTAMP    NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMP,
    total_fetched   INT,
    total_indexed   INT,
    status          VARCHAR(20)  NOT NULL DEFAULT 'running',
    error_message   TEXT,
    note            TEXT
);

CREATE TABLE IF NOT EXISTS law_sync_meta (
    id              SERIAL PRIMARY KEY,
    law_name        VARCHAR(100) NOT NULL,
    law_mst_id      VARCHAR(20)  NOT NULL UNIQUE,
    last_synced_at  TIMESTAMP,
    doc_count       INT DEFAULT 0,
    os_index        VARCHAR(100) DEFAULT 'law-articles',
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hazard_sync_meta (
    id              SERIAL PRIMARY KEY,
    api_type        VARCHAR(50)  NOT NULL UNIQUE,
    last_synced_at  TIMESTAMP,
    last_page       INT DEFAULT 0,
    doc_count       INT DEFAULT 0,
    os_index        VARCHAR(100) DEFAULT 'hazard-products',
    created_at      TIMESTAMP DEFAULT NOW()
);

-- 법령 조문 변경 이력. collect_law.py가 재수집 시 content_hash가 달라진 조문만
-- (덮어쓰기 전) 옛 내용을 여기 스냅샷으로 남긴다. 안 바뀐 조문은 행이 안 쌓인다.
CREATE TABLE IF NOT EXISTS law_article_history (
    id              SERIAL PRIMARY KEY,
    law_mst_id      VARCHAR(20)  NOT NULL,
    article_no      VARCHAR(20)  NOT NULL,
    clause_no       VARCHAR(10)  NOT NULL,
    old_content     TEXT,
    new_content     TEXT         NOT NULL,
    change_type     VARCHAR(20)  NOT NULL,   -- 'added' | 'modified' | 'removed'
    changed_at      TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_law_article_history_lookup
    ON law_article_history (law_mst_id, article_no, clause_no);

-- 수집 대상 법령 등록 (MST ID는 collect_law.py LAW_MAP 기준)
INSERT INTO law_sync_meta (law_name, law_mst_id) VALUES
    ('공중위생관리법', '259521'),
    ('화장품법',       '270323'),
    ('의료법',         '285327')
ON CONFLICT (law_mst_id) DO NOTHING;

-- 위해상품 API 타입 등록 (collect_hazard.py API_MAP 기준)
INSERT INTO hazard_sync_meta (api_type) VALUES
    ('recall'),
    ('ingredient')
ON CONFLICT (api_type) DO NOTHING;

SELECT 'DB 초기화 완료' AS result;
SELECT '  law_sync_meta:' AS "", count(*) FROM law_sync_meta;
SELECT '  hazard_sync_meta:' AS "", count(*) FROM hazard_sync_meta;
