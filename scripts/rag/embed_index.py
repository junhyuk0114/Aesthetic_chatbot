# -*- coding: utf-8 -*-
"""
embed_index.py
OpenSearch에 적재된 문서의 content 필드를 읽어 BGE-M3 임베딩을 생성하고
knn_vector 필드를 업데이트.

대상 인덱스: law-articles (hazard-products는 데이터 수집 후 추가)

사용법:
  python embed_index.py                      # law-articles 전체
  python embed_index.py --index law-articles # 특정 인덱스만
  python embed_index.py --sector 위생관리    # 특정 sector만
"""

# ============================================================
# 라이브러리 임포트
# ============================================================

import argparse
import os
import sys
import time
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))
from mazel_common import loadConfig, getOsClient


# ============================================================
# 상수 정의
# ============================================================

EMBED_API_PATH = "/api/embed"
BATCH_SIZE     = 16    # 한 번에 임베딩 생성할 문서 수
SCROLL_SIZE    = 200   # OpenSearch scroll 페이지 크기
SCROLL_TTL     = "5m"


# ============================================================
# Ollama 임베딩 생성
# ============================================================

def getEmbedding(ollamaHost, model, textList, maxRetry=5, sleepSec=2):
    """
    Ollama embed API로 텍스트 리스트의 임베딩 벡터를 생성.
    반환: 벡터 리스트 (list of list[float])
    """
    url     = ollamaHost.rstrip("/") + EMBED_API_PATH
    payload = {"model": model, "input": textList}
    lastErr = None

    for attempt in range(0, maxRetry):
        try:
            resp = requests.post(url, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            return data.get("embeddings", [])
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            lastErr = e
            if attempt < maxRetry - 1:
                waitSec = sleepSec * (attempt + 1)
                print(f"  [retry {attempt+1}/{maxRetry}] Ollama 연결 실패, {waitSec}s 대기")
                time.sleep(waitSec)
        except Exception as e:
            raise

    raise lastErr or RuntimeError("Ollama 임베딩 최대 재시도 초과")


# ============================================================
# OpenSearch scroll 조회
# ============================================================

def scrollDocs(osClient, indexName, sector=None):
    """
    OpenSearch scroll API로 인덱스 전체 문서를 배치 단위로 순회.
    knn_vector 가 비어 있거나 없는 문서만 대상으로 함.
    반환: 문서 dict 리스트 제너레이터 (각 원소: _id, content)
    """
    query = {
        "query": {
            "bool": {
                "must_not": [
                    {"exists": {"field": "knn_vector"}}
                ]
            }
        },
        "_source": ["content", "sector"],
        "size": SCROLL_SIZE,
    }

    if sector:
        query["query"]["bool"]["must"] = [{"term": {"sector": sector}}]

    resp     = osClient.search(index=indexName, body=query, scroll=SCROLL_TTL)
    scrollId = resp["_scroll_id"]
    hits     = resp["hits"]["hits"]

    while hits:
        for hit in hits:
            yield {"_id": hit["_id"], "content": hit["_source"].get("content", "")}
        resp     = osClient.scroll(scroll_id=scrollId, scroll=SCROLL_TTL)
        scrollId = resp["_scroll_id"]
        hits     = resp["hits"]["hits"]

    try:
        osClient.clear_scroll(scroll_id=scrollId)
    except Exception:
        pass


# ============================================================
# 배치 단위 임베딩 + 업데이트
# ============================================================

def bulkUpdateVectors(osClient, indexName, idList, vectorList):
    """
    bulk API로 knn_vector 필드 일괄 업데이트.
    반환: 성공 건수 (int)
    """
    bodyLines = []
    for i in range(0, len(idList)):
        bodyLines.append({"update": {"_index": indexName, "_id": idList[i]}})
        bodyLines.append({"doc": {"knn_vector": vectorList[i]}})

    result  = osClient.bulk(body=bodyLines, refresh=False)
    success = 0
    for item in result.get("items", []):
        if item.get("update", {}).get("status") in (200, 201):
            success += 1
    return success


def embedIndex(cfg, osClient, indexName, sector=None):
    """
    단일 인덱스에 대한 임베딩 생성 및 업데이트 실행.
    반환: 성공 업데이트 건수 (int)
    """
    ollamaHost = cfg['ollamaHost']
    model      = cfg['embedModel']

    print(f"\n[{indexName}] 임베딩 시작 (model={model}, batch={BATCH_SIZE})")
    if sector:
        print(f"  sector 필터: {sector}")

    totalSuccess = 0
    batchIds     = []
    batchTexts   = []
    docCount     = 0

    for doc in scrollDocs(osClient, indexName, sector):
        batchIds.append(doc["_id"])
        batchTexts.append(doc["content"])
        docCount += 1

        if len(batchIds) < BATCH_SIZE:
            continue

        # STEP A: 임베딩 생성
        try:
            vectors = getEmbedding(ollamaHost, model, batchTexts)
        except Exception as e:
            print({"success": False, "message": f"임베딩 생성 실패 (건너뜀): {e}"})
            batchIds   = []
            batchTexts = []
            continue

        # STEP B: OpenSearch 업데이트
        success       = bulkUpdateVectors(osClient, indexName, batchIds, vectors)
        totalSuccess += success
        print(f"  [{docCount}건 처리] 이번 배치: {success}/{len(batchIds)}건 완료")

        batchIds   = []
        batchTexts = []

    # 마지막 남은 배치 처리
    if batchIds:
        try:
            vectors = getEmbedding(ollamaHost, model, batchTexts)
            success       = bulkUpdateVectors(osClient, indexName, batchIds, vectors)
            totalSuccess += success
            print(f"  [{docCount}건 처리] 마지막 배치: {success}/{len(batchIds)}건 완료")
        except Exception as e:
            print({"success": False, "message": f"마지막 배치 임베딩 실패: {e}"})

    return totalSuccess


# ============================================================
# 메인
# ============================================================

def main():
    """
    임베딩 생성 메인 함수.
    --index 로 대상 인덱스, --sector 로 섹터 필터 지정 가능.
    """
    parser = argparse.ArgumentParser(description="BGE-M3 임베딩 생성 → OpenSearch knn_vector 업데이트")
    parser.add_argument("--index",  default="law-articles", help="대상 인덱스 (기본: law-articles)")
    parser.add_argument("--sector", default=None,           help="섹터 필터 (예: 위생관리)")
    args = parser.parse_args()

    # STEP 1: 설정 로드
    cfg = loadConfig()

    # STEP 2: 클라이언트 초기화
    osClient = getOsClient(cfg)

    # STEP 3: Ollama 연결 확인
    try:
        testResp = requests.get(cfg['ollamaHost'].rstrip("/") + "/api/tags", timeout=5)
        testResp.raise_for_status()
        print(f"[INFO] Ollama 연결 확인 (model={cfg['embedModel']})")
    except Exception as e:
        print({"success": False, "message": f"Ollama 연결 실패: {e}"})
        sys.exit(1)

    # STEP 4: 현재 knn_vector 없는 문서 수 확인
    countResp = osClient.count(
        index=args.index,
        body={"query": {"bool": {"must_not": [{"exists": {"field": "knn_vector"}}]}}}
    )
    remaining = countResp.get("count", 0)
    print(f"[INFO] 임베딩 대상 문서 수: {remaining}건")

    if remaining == 0:
        print("[INFO] 임베딩이 필요한 문서가 없습니다.")
        sys.exit(0)

    # STEP 5: 임베딩 실행
    totalSuccess = embedIndex(cfg, osClient, args.index, args.sector)

    # STEP 6: 결과 출력
    print(f"\n[완료] knn_vector 업데이트: {totalSuccess}건")


if __name__ == "__main__":
    main()
