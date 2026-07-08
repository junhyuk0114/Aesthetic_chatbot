# -*- coding: utf-8 -*-
"""
qa_cache.py
질문-답변 시맨틱 캐시.

BGE-M3 임베딩으로 과거 질문과의 코사인 유사도를 비교해, 임계값 이상으로
비슷한 과거 질문이 있으면 RAG 파이프라인(검색+LLM) 재실행 없이 과거 답변을
그대로 반환한다.

저장 위치:
- OpenSearch (qa-cache 인덱스): 질문 임베딩 + 메타 → 유사도 검색용
- Redis                       : 실제 답변 payload(JSON) → answer_id로 빠르게 조회

법률·안전 자문 도메인 특성상 질문이 미묘하게 달라지면 답변도 달라질 수 있어,
임계값(QA_CACHE_THRESHOLD, 기본 0.95)을 보수적으로 높게 잡는다.
"""

# ============================================================
# 라이브러리 임포트
# ============================================================

import json
import os
import sys
import time
import uuid

import redis

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))
from search_hybrid import embedQuery


# ============================================================
# 상수 정의
# ============================================================

CACHE_INDEX = "qa-cache"


# ============================================================
# 인덱스 / 클라이언트 초기화
# ============================================================

def ensureCacheIndex(osClient):
    """qa-cache 인덱스가 없으면 생성."""
    if osClient.indices.exists(index=CACHE_INDEX):
        return

    mapping = {
        "settings": {
            "number_of_shards":   1,
            "number_of_replicas": 0,
            "index.knn":          True,
        },
        "mappings": {
            "properties": {
                "doc_type":   {"type": "keyword"},   # "law" | "hazard"
                "scope":      {"type": "keyword"},   # sector(law) / apiType(hazard), 없으면 "_all"
                "query":      {"type": "text"},
                "answer_id":  {"type": "keyword"},
                "created_at": {"type": "date"},
                "knn_vector": {
                    "type":      "knn_vector",
                    "dimension": 1024,
                    "method": {
                        "name":       "hnsw",
                        "space_type": "cosinesimil",
                        "engine":     "lucene",
                    },
                },
            }
        },
    }
    osClient.indices.create(index=CACHE_INDEX, body=mapping)
    print(f"[INFO] 인덱스 생성 완료: {CACHE_INDEX}")


def getRedisClient(cfg):
    """설정값으로 Redis 클라이언트 생성."""
    return redis.Redis(
        host=cfg['redisHost'],
        port=cfg['redisPort'],
        db=cfg['redisDb'],
        password=cfg['redisPassword'] or None,
        decode_responses=True,
    )


# ============================================================
# 캐시 조회 / 적재
# ============================================================

def lookupCache(osClient, redisClient, cfg, docType, queryText, scope=None):
    """
    과거 질문 중 의미상 가장 유사한 질문을 찾아, 임계값 이상이면 캐시된 답변을 반환.
    docType : "law" | "hazard"
    scope   : sector(law) 또는 apiType(hazard) 필터, None이면 전체
    반환    : (cachedResult 또는 None, queryVector) — queryVector는 캐시 미스 시 storeCache에 재사용
    """
    queryVector = embedQuery(cfg, queryText)

    try:
        # scope가 None("전체" 검색)이어도 storeCache와 동일하게 "_all"로 취급해
        # 반드시 필터링한다. 그냥 조건부로 필터를 생략하면, "전체" 조회가
        # 특정 sector/apiType으로 좁혀서 캐싱된(=범위가 다른) 답변과 잘못 매칭될 수 있다.
        filters = [
            {"term": {"doc_type": docType}},
            {"term": {"scope": scope or "_all"}},
        ]

        body = {
            "size":    1,
            "_source": ["answer_id"],
            "query": {
                "knn": {
                    "knn_vector": {
                        "vector": queryVector,
                        "k":      1,
                        "filter": {"bool": {"filter": filters}},
                    }
                }
            },
        }
        resp = osClient.search(index=CACHE_INDEX, body=body)
        hits = resp["hits"]["hits"]
        if not hits or hits[0]["_score"] < cfg['qaCacheThreshold']:
            return None, queryVector

        answerId = hits[0]["_source"]["answer_id"]
        cached   = redisClient.get(f"qa:{answerId}")
        if not cached:
            return None, queryVector

        print(f"[CACHE HIT] score={hits[0]['_score']:.4f} answer_id={answerId}")
        return json.loads(cached), queryVector

    except Exception as e:
        print(f"[WARN] 캐시 조회 실패, RAG 정상 실행으로 진행: {e}")
        return None, queryVector


def storeCache(osClient, redisClient, cfg, docType, queryText, ragResult, scope=None, queryVector=None):
    """새 질문-답변을 캐시에 적재 (Redis: 답변 payload, OpenSearch: 임베딩+메타)."""
    try:
        if queryVector is None:
            queryVector = embedQuery(cfg, queryText)

        answerId = uuid.uuid4().hex
        redisClient.setex(
            f"qa:{answerId}",
            cfg['qaCacheTtlSec'],
            json.dumps(ragResult, ensure_ascii=False),
        )
        osClient.index(
            index=CACHE_INDEX,
            body={
                "doc_type":   docType,
                "scope":      scope or "_all",
                "query":      queryText,
                "answer_id":  answerId,
                "created_at": int(time.time() * 1000),
                "knn_vector": queryVector,
            },
        )
    except Exception as e:
        print(f"[WARN] 캐시 저장 실패 (응답에는 영향 없음): {e}")
