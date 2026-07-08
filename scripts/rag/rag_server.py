# -*- coding: utf-8 -*-
"""
rag_server.py
FastAPI RAG 서버 — Spring MVC에서 HTTP로 호출하는 내부 서비스.
포트 5000에서 실행. Swagger UI: http://localhost:5000/docs

엔드포인트:
  POST /rag/query  : RAG 답변 생성 (법령 + 안전정보 통합 검색, LLM 호출 1회)
  GET  /rag/health : 서버 상태 확인
  GET  /rag/status : 인덱스 통계

사용법:
  python rag_server.py
  uvicorn rag_server:app --host 0.0.0.0 --port 5000 --reload
"""

# ============================================================
# 라이브러리 임포트
# ============================================================

import os
import sys
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))
from mazel_common import loadConfig, getOsClient
from search_hybrid import ensurePipeline
from rag_pipeline  import runCombinedRag
from qa_cache       import ensureCacheIndex, getRedisClient, lookupCache, storeCache


# ============================================================
# FastAPI 앱 및 공유 클라이언트 초기화
# ============================================================

app = FastAPI(
    title="에스테틱 법률 안전 챗봇 — RAG API",
    description="공중위생관리법·화장품법·의료법 기반 RAG 답변 서비스 (마젤원향)",
    version="1.0.0",
)

cfg         = None
osClient    = None
redisClient = None


@app.on_event("startup")
def startup():
    """서버 시작 시 OpenSearch/Redis 클라이언트 및 파이프라인·캐시 인덱스 초기화."""
    global cfg, osClient, redisClient
    cfg         = loadConfig()
    osClient    = getOsClient(cfg)
    redisClient = getRedisClient(cfg)
    ensurePipeline(osClient)
    ensureCacheIndex(osClient)
    print("[INFO] RAG 서버 초기화 완료")


# ============================================================
# 요청/응답 스키마
# ============================================================

class QueryRequest(BaseModel):
    """RAG 질문 요청 스키마"""
    query:  str
    sector: Optional[str] = None
    topk:   Optional[int] = 5

    class Config:
        json_schema_extra = {
            "example": {
                "query":  "인스타에 여드름 치료 전문샵이라고 써도 되나요?",
                "sector": None,
                "topk":   5,
            }
        }


class SearchResult(BaseModel):
    """개별 검색 결과 조문"""
    rank:           int
    score:          float
    law_name:       str
    article_no:     str
    clause_no:      str
    sector:         str
    title:          str
    content:        str
    effective_date: Optional[str]


class SummaryPoint(BaseModel):
    """카드 렌더링용 포인트 1개 (소제목 + 본문)"""
    title: str
    body:  str


class ListItem(BaseModel):
    """개수 지정 질문("N개/가지/건") 응답의 목록 항목 1개"""
    name: str
    desc: str


class QueryResponse(BaseModel):
    """RAG 답변 응답 스키마 (카드 렌더링용 구조화 답변 / 개수 지정 목록 답변)"""
    success:          bool
    summary:          str = ""
    points:           list[SummaryPoint] = []
    raw_fallback:     str = ""   # LLM이 형식을 안 지켰을 때만 값이 들어감 (프론트 fallback 렌더링용)
    list_items:       list[ListItem] = []
    requested_count:  Optional[int] = None
    truncated_notice: str = ""   # 요청 개수가 MAX_HAZARD_TOP_K를 초과해 검색 단계에서 이미 잘렸을 때만 값이 들어감
    sources:          list[str]
    results:          list[SearchResult]
    suggestions:      list[str] = []


class StatusResponse(BaseModel):
    """서버 상태 응답 스키마"""
    success:      bool
    law_articles: int
    embedded:     int
    embed_model:  str
    llm_model:    str


# ============================================================
# 엔드포인트
# ============================================================

@app.get(
    "/rag/health",
    summary="서버 상태 확인",
    tags=["시스템"],
)
def health():
    """RAG 서버 및 모델 상태를 반환합니다."""
    return {"status": "ok", "model": cfg['llmModel'] if cfg else "unknown"}


@app.get(
    "/rag/status",
    response_model=StatusResponse,
    summary="인덱스 통계 조회",
    tags=["시스템"],
)
def status():
    """OpenSearch 인덱스 문서 수 및 임베딩 현황을 반환합니다."""
    try:
        docCount = osClient.count(
            index="law-articles",
            body={"query": {"match_all": {}}}
        )["count"]
        vecCount = osClient.count(
            index="law-articles",
            body={"query": {"exists": {"field": "knn_vector"}}}
        )["count"]
        return StatusResponse(
            success=True,
            law_articles=docCount,
            embedded=vecCount,
            embed_model=cfg['embedModel'],
            llm_model=cfg['llmModel'],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post(
    "/rag/query",
    response_model=QueryResponse,
    summary="RAG 답변 생성",
    tags=["챗봇"],
)
def ragQuery(req: QueryRequest):
    """
    사용자 질문을 받아 관련 법령을 검색하고 Gemma4:e4b로 답변을 생성합니다.

    - **query**: 사용자 질문 텍스트 (필수)
    - **sector**: 검색 범위 필터 (위생관리 / 화장품규제 / 의료행위, 미입력 시 전체)
    - **topk**: 참조할 법령 조문 수 (기본 5)
    """
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query가 비어 있습니다.")

    try:
        cached, queryVector = lookupCache(osClient, redisClient, cfg, "law", req.query, scope=req.sector)
        if cached:
            ragResult = cached
        else:
            ragResult = runCombinedRag(osClient, cfg, req.query, sector=req.sector, topK=req.topk)
            storeCache(osClient, redisClient, cfg, "law", req.query, ragResult,
                       scope=req.sector, queryVector=queryVector)

        return QueryResponse(
            success=True,
            summary=ragResult.get("summary", ""),
            points=[SummaryPoint(**p) for p in ragResult.get("points", [])],
            raw_fallback=ragResult.get("raw_fallback", ""),
            list_items=[ListItem(**i) for i in ragResult.get("list_items", [])],
            requested_count=ragResult.get("requested_count"),
            truncated_notice=ragResult.get("truncated_notice", ""),
            sources=ragResult["sources"],
            results=[SearchResult(**r) for r in ragResult["results"]],
            suggestions=ragResult.get("suggestions", []),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 메인
# ============================================================

if __name__ == "__main__":
    uvicorn.run("rag_server:app", host="0.0.0.0", port=5000, reload=False)
