# -*- coding: utf-8 -*-
"""
search_hybrid.py
BM25 + kNN 하이브리드 검색 구현 모듈 및 CLI 테스트 도구.

OpenSearch neural-search 플러그인의 hybrid 쿼리와
normalization-processor 파이프라인을 사용.

사용법 (CLI 테스트):
  python search_hybrid.py "인스타에 치료 전문샵 표현 써도 되나요?"
  python search_hybrid.py "위생사 면허" --sector 위생관리 --topk 5
"""

# ============================================================
# 라이브러리 임포트
# ============================================================

import argparse
import os
import sys
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))
from mazel_common import loadConfig, getOsClient


# ============================================================
# 상수 정의
# ============================================================

INDEX_NAME        = "law-articles"
HAZARD_INDEX_NAME = "hazard-products"
PIPELINE_ID       = "law-hybrid-pipeline"
EMBED_API_PATH    = "/api/embed"

# BM25 : kNN 가중치 (합계 1.0)
WEIGHT_BM25 = 0.3
WEIGHT_KNN  = 0.7


# ============================================================
# 검색 파이프라인 설정
# ============================================================

def ensurePipeline(osClient):
    """
    normalization-processor 검색 파이프라인이 없으면 생성.
    BM25(0.3)와 kNN(0.7) 점수를 min_max 정규화 후 가중 평균으로 결합.
    """
    try:
        osClient.transport.perform_request("GET", f"/_search/pipeline/{PIPELINE_ID}")
        return
    except Exception:
        pass

    pipeline = {
        "description": "에스테틱 법령 하이브리드 검색 파이프라인",
        "phase_results_processors": [
            {
                "normalization-processor": {
                    "normalization": {
                        "technique": "min_max"
                    },
                    "combination": {
                        "technique": "arithmetic_mean",
                        "parameters": {
                            "weights": [WEIGHT_BM25, WEIGHT_KNN]
                        }
                    }
                }
            }
        ]
    }
    osClient.transport.perform_request(
        "PUT",
        f"/_search/pipeline/{PIPELINE_ID}",
        body=pipeline
    )
    print(f"[INFO] 검색 파이프라인 생성: {PIPELINE_ID}")


# ============================================================
# 임베딩 생성
# ============================================================

def embedQuery(cfg, queryText):
    """
    Ollama BGE-M3 모델로 쿼리 텍스트의 임베딩 벡터 생성.
    반환: 벡터 (list[float])
    """
    url     = cfg['ollamaHost'].rstrip("/") + EMBED_API_PATH
    payload = {"model": cfg['embedModel'], "input": [queryText]}
    resp    = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    embeddings = resp.json().get("embeddings", [])
    if not embeddings:
        raise ValueError("Ollama 임베딩 응답이 비어 있습니다.")
    return embeddings[0]


# ============================================================
# 하이브리드 검색
# ============================================================

def searchHybrid(osClient, cfg, queryText, sector=None, topK=5):
    """
    BM25 + kNN 하이브리드 검색 실행.
    queryText : 사용자 질문 문자열
    sector    : 필터링할 sector (None이면 전체 검색)
    topK      : 반환할 최대 문서 수
    반환      : 검색 결과 dict 리스트
    """
    # STEP A: 쿼리 임베딩 생성
    queryVector = embedQuery(cfg, queryText)

    # STEP B: 하이브리드 쿼리 구성
    knnQuery = {
        "knn": {
            "knn_vector": {
                "vector": queryVector,
                "k":      topK * 2,    # 충분히 후보 확보 후 파이프라인에서 재정렬
            }
        }
    }

    if sector:
        knnQuery["knn"]["knn_vector"]["filter"] = {
            "term": {"sector": sector}
        }

    hybridQuery = {
        "hybrid": {
            "queries": [
                {
                    "bool": {
                        "must": [
                            {"match": {"content": {"query": queryText}}}
                        ],
                        "filter": [{"term": {"sector": sector}}] if sector else []
                    }
                },
                knnQuery
            ]
        }
    }

    body = {
        "size":    topK,
        "_source": ["law_name", "article_no", "clause_no", "title",
                    "content", "sector", "effective_date"],
        "query":   hybridQuery,
    }

    # STEP C: 검색 실행 (파이프라인 적용)
    resp = osClient.search(
        index  = INDEX_NAME,
        body   = body,
        params = {"search_pipeline": PIPELINE_ID}
    )

    # STEP D: 결과 파싱
    hits    = resp["hits"]["hits"]
    results = []
    for i in range(0, len(hits)):
        hit = hits[i]
        src = hit["_source"]
        results.append({
            "rank":         i + 1,
            "score":        round(hit["_score"], 4),
            "law_name":     src.get("law_name", ""),
            "article_no":   src.get("article_no", ""),
            "clause_no":    src.get("clause_no", ""),
            "sector":       src.get("sector", ""),
            "title":        src.get("title", ""),
            "content":      src.get("content", ""),
            "effective_date": src.get("effective_date", ""),
        })
    return results


# ============================================================
# 하이브리드 검색 (hazard-products : 회수·판매중지 / 사용제한 원료)
# ============================================================

def searchHazardHybrid(osClient, cfg, queryText, apiType=None, country="한국", topK=5):
    """
    hazard-products 인덱스 BM25 + kNN 하이브리드 검색 실행.
    queryText : 사용자 질문 문자열
    apiType   : "recall"(회수·판매중지) 또는 "ingredient"(사용제한 원료) 필터, None이면 전체
    country   : 사용제한 원료의 규제 국가 필터 (기본값 "한국"). country_name 필드가 없는
                문서(회수·판매중지는 국가 구분이 없음)는 필터와 무관하게 항상 포함됨.
                전체 국가를 보려면 country=None으로 명시.
    topK      : 반환할 최대 문서 수
    반환      : 검색 결과 dict 리스트
    """
    queryVector = embedQuery(cfg, queryText)

    filters = []
    if apiType:
        filters.append({"term": {"api_type": apiType}})
    if country:
        filters.append({
            "bool": {
                "should": [
                    {"term": {"country_name": country}},
                    {"bool": {"must_not": {"exists": {"field": "country_name"}}}}
                ],
                "minimum_should_match": 1
            }
        })

    knnQuery = {
        "knn": {
            "knn_vector": {
                "vector": queryVector,
                "k":      topK * 2,
            }
        }
    }
    if filters:
        knnQuery["knn"]["knn_vector"]["filter"] = {"bool": {"filter": filters}}

    hybridQuery = {
        "hybrid": {
            "queries": [
                {
                    "bool": {
                        "must":   [{"match": {"content": {"query": queryText}}}],
                        "filter": filters
                    }
                },
                knnQuery
            ]
        }
    }

    body = {
        "size":    topK,
        "_source": ["api_type", "product_name", "company_name", "ingredient_name",
                    "ingredient_eng_name", "cas_no", "country_name", "regulate_type",
                    "hazard_detail", "content", "sector", "report_date", "recall_end_date"],
        "query":   hybridQuery,
    }

    resp = osClient.search(
        index  = HAZARD_INDEX_NAME,
        body   = body,
        params = {"search_pipeline": PIPELINE_ID}
    )

    hits    = resp["hits"]["hits"]
    results = []
    for i in range(0, len(hits)):
        hit = hits[i]
        src = hit["_source"]
        results.append({
            "rank":                i + 1,
            "score":               round(hit["_score"], 4),
            "api_type":            src.get("api_type", ""),
            "product_name":        src.get("product_name", ""),
            "company_name":        src.get("company_name", ""),
            "ingredient_name":     src.get("ingredient_name", ""),
            "ingredient_eng_name": src.get("ingredient_eng_name", ""),
            "cas_no":              src.get("cas_no", ""),
            "country_name":        src.get("country_name", ""),
            "regulate_type":       src.get("regulate_type", ""),
            "hazard_detail":       src.get("hazard_detail", ""),
            "content":             src.get("content", ""),
            "sector":              src.get("sector", ""),
            "report_date":         src.get("report_date", ""),
            "recall_end_date":     src.get("recall_end_date", ""),
        })
    return results


# ============================================================
# 결과 출력 (CLI용)
# ============================================================

def printResults(results, queryText):
    """검색 결과를 사람이 읽기 좋은 형태로 출력."""
    print(f"\n{'='*60}")
    print(f"  검색어: {queryText}")
    print(f"  결과 수: {len(results)}건")
    print(f"{'='*60}")
    for i in range(0, len(results)):
        r = results[i]
        print(f"\n[{r['rank']}위] score={r['score']} | {r['law_name']} 제{r['article_no']}조 {r['clause_no']}항 [{r['sector']}]")
        print(f"  제목: {r['title']}")
        print(f"  내용: {r['content'][:200]}{'...' if len(r['content']) > 200 else ''}")
        print(f"  시행일: {r['effective_date']}")


# ============================================================
# 메인 (CLI 테스트)
# ============================================================

def main():
    """
    하이브리드 검색 CLI 테스트 함수.
    """
    parser = argparse.ArgumentParser(description="에스테틱 법령 하이브리드 검색 테스트")
    parser.add_argument("query",             help="검색 질문")
    parser.add_argument("--sector", default=None,
                        help="sector 필터 (위생관리/화장품규제/의료행위)")
    parser.add_argument("--topk",   default=5, type=int, help="결과 수 (기본: 5)")
    args = parser.parse_args()

    # STEP 1: 설정 로드 및 클라이언트 초기화
    cfg      = loadConfig()
    osClient = getOsClient(cfg)

    # STEP 2: 검색 파이프라인 확인/생성
    ensurePipeline(osClient)

    # STEP 3: 하이브리드 검색 실행
    print(f"[검색 중] '{args.query}'")
    try:
        results = searchHybrid(osClient, cfg, args.query, sector=args.sector, topK=args.topk)
    except Exception as e:
        print({"success": False, "message": f"검색 실패: {e}"})
        sys.exit(1)

    # STEP 4: 결과 출력
    printResults(results, args.query)


if __name__ == "__main__":
    main()
