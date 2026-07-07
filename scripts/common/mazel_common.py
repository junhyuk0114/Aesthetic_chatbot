# -*- coding: utf-8 -*-
"""
mazel_common.py
마젤원향 에스테틱 법률 안전 챗봇 — 공통 유틸리티

포함 함수:
- loadConfig      : .env 로드 → 설정 딕셔너리 반환
- retryGet        : GET 요청 실패 시 최대 N회 재시도 (선형 백오프)
- getOsClient     : OpenSearch 클라이언트 반환
- getDbConn       : PostgreSQL 연결 반환
- recordLog       : collection_log 테이블에 수집 이력 기록
- updateLawMeta   : law_sync_meta 동기화 상태 업데이트
- updateHazardMeta: hazard_sync_meta 동기화 상태 업데이트
- recordLawHistory: law_article_history 테이블에 조문 변경 이력 기록
"""

# ============================================================
# 라이브러리 임포트
# ============================================================

import os
import time
import requests
import psycopg2
from dotenv import load_dotenv
from opensearchpy import OpenSearch


# ============================================================
# 설정 로드
# ============================================================

def loadConfig():
    """
    프로젝트 루트의 .env 파일을 로드하고 전체 설정값을 딕셔너리로 반환.
    .env 값이 없으면 기본값 사용.
    """
    load_dotenv()

    cfg = {
        # PostgreSQL
        'dbHost':     os.getenv("DB_HOST",     "localhost"),
        'dbPort':     int(os.getenv("DB_PORT", 5432)),
        'dbName':     os.getenv("DB_NAME",     "mazel_esthetic_db"),
        'dbUser':     os.getenv("DB_USER",     "mazel_user"),
        'dbPassword': os.getenv("DB_PASSWORD", "mazel2026!"),

        # OpenSearch
        'osHost':     os.getenv("OS_HOST",     "https://localhost:9200"),
        'osUser':     os.getenv("OS_USER",     "admin"),
        'osPassword': os.getenv("OS_PASSWORD", "Secure#Open2024!"),

        # Ollama
        'ollamaHost': os.getenv("OLLAMA_HOST",  "http://localhost:11434"),
        'embedModel': os.getenv("EMBED_MODEL",  "bge-m3"),
        'llmModel':   os.getenv("LLM_MODEL",    "gemma4:e4b"),

        # Redis (질문-답변 시맨틱 캐시)
        'redisHost':        os.getenv("REDIS_HOST",     "localhost"),
        'redisPort':        int(os.getenv("REDIS_PORT", 6379)),
        'redisDb':          int(os.getenv("REDIS_DB",   0)),
        'redisPassword':    os.getenv("REDIS_PASSWORD", ""),
        'qaCacheThreshold': float(os.getenv("QA_CACHE_THRESHOLD", 0.95)),
        'qaCacheTtlSec':    int(os.getenv("QA_CACHE_TTL_SEC", 60 * 60 * 24 * 7)),

        # 공공데이터 API
        'lawApiKey':    os.getenv("LAW_API_KEY",         ""),
        'publicApiKey': os.getenv("PUBLIC_DATA_API_KEY", ""),
    }
    return cfg


# ============================================================
# API 재시도 유틸
# ============================================================

def retryGet(url, params, maxRetry=5, sleepSec=2):
    """
    GET 요청 실패 시 최대 maxRetry회 재시도 (선형 백오프: 2s, 4s, 6s...).
    - ConnectionError / Timeout / 429 → 재시도
    - 그 외 HTTPError (4xx/5xx)       → 즉시 raise
    """
    lastErr = None
    for attempt in range(0, maxRetry):
        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 429:
                waitSec = sleepSec * (attempt + 2)
                print(f"  [retry {attempt+1}/{maxRetry}] Rate limit, {waitSec}s 대기")
                time.sleep(waitSec)
                lastErr = requests.exceptions.HTTPError("429 Too Many Requests")
                continue
            resp.raise_for_status()
            return resp
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError) as e:
            lastErr = e
            if attempt < maxRetry - 1:
                waitSec = sleepSec * (attempt + 1)
                print(f"  [retry {attempt+1}/{maxRetry}] {type(e).__name__}, {waitSec}s 대기")
                time.sleep(waitSec)
        except requests.exceptions.HTTPError:
            raise
        except Exception as e:
            raise
    raise lastErr or RuntimeError("retryGet 최대 재시도 초과")


# ============================================================
# OpenSearch 클라이언트
# ============================================================

def getOsClient(cfg):
    """
    OpenSearch 클라이언트 객체 반환.
    개발 환경 데모 인증서 사용으로 SSL 검증 비활성화.
    """
    stripped = cfg['osHost'].replace("https://", "").replace("http://", "")
    useSSL   = cfg['osHost'].startswith("https")
    if ":" in stripped:
        rawHost, rawPort = stripped.rsplit(":", 1)
        rawPort = int(rawPort)
    else:
        rawHost = stripped
        rawPort = 9200

    client = OpenSearch(
        hosts=[{"host": rawHost, "port": rawPort}],
        http_auth=(cfg['osUser'], cfg['osPassword']),
        use_ssl=useSSL,
        verify_certs=False,
        ssl_show_warn=False,
    )
    return client


# ============================================================
# PostgreSQL 연결
# ============================================================

def getDbConn(cfg):
    """
    PostgreSQL 연결 객체 반환.
    """
    conn = psycopg2.connect(
        host=cfg['dbHost'],
        port=cfg['dbPort'],
        dbname=cfg['dbName'],
        user=cfg['dbUser'],
        password=cfg['dbPassword'],
    )
    return conn


# ============================================================
# 수집 이력 기록
# ============================================================

def recordLog(conn, source, status, fetched=0, indexed=0, error=None):
    """
    collection_log 테이블에 수집 실행 결과 기록.
    source  : API 식별자 (예: 'law_259521', 'hazard_recall')
    status  : 'success' | 'failed'
    fetched : API에서 가져온 건수
    indexed : OpenSearch에 인덱싱 성공 건수
    """
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO collection_log
               (source, finished_at, total_fetched, total_indexed, status, error_message)
               VALUES (%s, NOW(), %s, %s, %s, %s)""",
            (source, fetched, indexed, status, error),
        )
        conn.commit()
        cursor.close()
    except Exception as e:
        conn.rollback()
        print({"success": False, "message": f"recordLog 실패: {e}"})


def updateLawMeta(conn, mstId, docCount):
    """
    law_sync_meta 테이블의 last_synced_at 및 doc_count 업데이트.
    mstId    : 법제처 법령 ID
    docCount : 인덱싱된 조문 수
    """
    try:
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE law_sync_meta
               SET last_synced_at = NOW(), doc_count = %s
               WHERE law_mst_id = %s""",
            (docCount, mstId),
        )
        conn.commit()
        cursor.close()
    except Exception as e:
        conn.rollback()
        print({"success": False, "message": f"updateLawMeta 실패: {e}"})


def updateHazardMeta(conn, apiType, docCount):
    """
    hazard_sync_meta 테이블의 last_synced_at 및 doc_count 업데이트.
    apiType  : 'recall' | 'unfit'
    docCount : 인덱싱된 제품 수
    """
    try:
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE hazard_sync_meta
               SET last_synced_at = NOW(), doc_count = %s
               WHERE api_type = %s""",
            (docCount, apiType),
        )
        conn.commit()
        cursor.close()
    except Exception as e:
        conn.rollback()
        print({"success": False, "message": f"updateHazardMeta 실패: {e}"})


# ============================================================
# 법령 조문 변경 이력 기록
# ============================================================

def recordLawHistory(conn, lawMstId, articleNo, clauseNo, oldContent, newContent, changeType):
    """
    law_article_history 테이블에 조문 변경 이력 기록.
    재수집 시 content_hash가 달라진 조문만 호출됨(collect_law.py 참고).
    changeType : 'added' | 'modified' | 'removed'
    """
    try:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO law_article_history
               (law_mst_id, article_no, clause_no, old_content, new_content, change_type)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (lawMstId, articleNo, clauseNo, oldContent, newContent, changeType),
        )
        conn.commit()
        cursor.close()
    except Exception as e:
        conn.rollback()
        print({"success": False, "message": f"recordLawHistory 실패: {e}"})
