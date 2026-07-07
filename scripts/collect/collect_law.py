# -*- coding: utf-8 -*-
"""
collect_law.py
법제처 API에서 법령 조문을 수집하여 OpenSearch law-articles 인덱스에 적재.
PostgreSQL collection_log / law_sync_meta 에 수집 이력 기록.

사용법:
  python collect_law.py            # 3개 법령 전체 수집
  python collect_law.py --mst 259521  # 특정 법령만 수집
"""

# ============================================================
# 라이브러리 임포트
# ============================================================

import argparse
import hashlib
import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))
from mazel_common import loadConfig, retryGet, getOsClient, getDbConn, recordLog, updateLawMeta, recordLawHistory
from opensearchpy import helpers


# ============================================================
# 상수 정의
# ============================================================

LAW_API_BASE = "https://www.law.go.kr/DRF/lawService.do"
INDEX_NAME   = "law-articles"

LAW_MAP = {
    "259521": {"name": "공중위생관리법", "sector": "위생관리"},
    "270323": {"name": "화장품법",       "sector": "화장품규제"},
    "285327": {"name": "의료법",         "sector": "의료행위"},
}


# ============================================================
# OpenSearch 인덱스 생성
# ============================================================

def ensureIndex(osClient):
    """
    law-articles 인덱스가 없으면 생성.
    knn_vector 필드(1024차원)는 embed_index.py 에서 채워짐.
    이미 있는 인덱스라도 content_hash 필드는 매핑에 없으면 추가 시도(있으면 무시, 안전한 add-only 연산).
    """
    if osClient.indices.exists(index=INDEX_NAME):
        osClient.indices.put_mapping(
            index=INDEX_NAME,
            body={"properties": {"content_hash": {"type": "keyword"}}},
        )
        return

    mapping = {
        "settings": {
            "number_of_shards":   1,
            "number_of_replicas": 0,
            "index.knn":          True,
        },
        "mappings": {
            "properties": {
                "law_name":           {"type": "keyword"},
                "law_mst_id":         {"type": "keyword"},
                "sector":             {"type": "keyword"},
                "article_no":         {"type": "keyword"},
                "clause_no":          {"type": "keyword"},
                "title":              {"type": "text", "analyzer": "standard"},
                "content":            {"type": "text", "analyzer": "standard"},
                "content_hash":       {"type": "keyword"},
                "effective_date":     {"type": "date", "format": "yyyyMMdd||yyyy-MM-dd"},
                "promulgation_date":  {"type": "date", "format": "yyyyMMdd||yyyy-MM-dd"},
                "indexed_at":         {"type": "date"},
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
    osClient.indices.create(index=INDEX_NAME, body=mapping)
    print(f"[INFO] 인덱스 생성 완료: {INDEX_NAME}")


# ============================================================
# 법령 수집
# ============================================================

def fetchLaw(cfg, mstId):
    """
    법제처 API에서 법령 전체 JSON 수신 (target=law).
    반환: API 응답 dict
    """
    params = {
        "OC":     cfg['lawApiKey'],
        "target": "law",
        "MST":    mstId,
        "type":   "JSON",
    }
    resp = retryGet(LAW_API_BASE, params=params)
    return resp.json()


def parseDate(rawDate):
    """
    날짜 문자열을 yyyyMMdd 또는 yyyy-MM-dd 형태로 정규화.
    빈 문자열·None 은 None 반환.
    """
    if not rawDate:
        return None
    cleaned = str(rawDate).strip().replace("-", "")
    if len(cleaned) == 8 and cleaned.isdigit():
        return cleaned
    return None


def hashContent(content):
    """content 문자열의 SHA-256 해시(hex). 재수집 시 변경 여부 비교용."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def parseClauses(lawData, mstId, lawInfo):
    """
    API 응답 dict에서 항(clause) 단위 OpenSearch 문서 리스트 생성.
    항이 없는 조문은 조문 전체를 단일 문서로 처리 (clause_no='0').

    반환: bulk 인덱싱용 dict 리스트
    """
    lawBlock        = lawData.get("법령", {})
    basicInfo       = lawBlock.get("기본정보", {})
    articleList     = lawBlock.get("조문", {}).get("조문단위", [])

    effectiveDate    = parseDate(basicInfo.get("시행일자", ""))
    promulgationDate = parseDate(basicInfo.get("공포일자", ""))
    lawName          = lawInfo['name']
    sector           = lawInfo['sector']

    docs = []
    for i in range(0, len(articleList)):
        art       = articleList[i]
        artKey    = str(art.get("조문키", "")).strip()        # 고유 식별자 (예: 0003021)
        articleNo = str(art.get("조문번호", "")).strip()
        branchNo  = str(art.get("조문가지번호", "")).strip()  # 의2, 의3 등
        title     = str(art.get("조문제목", "")).strip()
        clauseList = art.get("항", [])                        # 실제 키는 '항' (조문항 아님)
        if isinstance(clauseList, dict):                      # 단일 항일 때 dict로 반환되는 경우 처리
            clauseList = [clauseList]

        # 조문번호 표시: 제3조의2 → "3의2"
        if branchNo:
            displayNo = f"{articleNo}의{branchNo}"
        else:
            displayNo = articleNo

        if not clauseList:
            content = str(art.get("조문내용", "")).strip()
            if not content:
                continue
            fullContent = f"제{displayNo}조({title})\n{content}".strip()
            docId = f"law_{mstId}_{artKey}_0"
            docs.append({
                "_index": INDEX_NAME,
                "_id":    docId,
                "_source": {
                    "law_name":          lawName,
                    "law_mst_id":        mstId,
                    "sector":            sector,
                    "article_no":        displayNo,
                    "clause_no":         "0",
                    "title":             title,
                    "content":           fullContent,
                    "content_hash":      hashContent(fullContent),
                    "effective_date":    effectiveDate,
                    "promulgation_date": promulgationDate,
                    "indexed_at":        datetime.now().isoformat(),
                },
            })
        else:
            for j in range(0, len(clauseList)):
                clause   = clauseList[j]
                clauseNo = str(j + 1)
                content  = str(clause.get("항내용", "")).strip()
                if not content:
                    continue

                # 호(항 하위 목록, 예: "다음 각 호의 어느 하나에 해당하는...") 내용 이어붙이기.
                # 안 하면 "① ...다음 각 호의 어느 하나에 해당하는 표시를 하여서는 아니 된다"처럼
                # 실제 금지/처벌 항목 없이 도입부 문장만 남아 검색·답변에 못 쓰임.
                itemList = clause.get("호", [])
                if isinstance(itemList, dict):
                    itemList = [itemList]
                for item in itemList:
                    itemContent = str(item.get("호내용", "")).strip()
                    if itemContent:
                        content += "\n" + itemContent

                    # 목(호 하위 목록, 예: "가.", "나." 항목) 내용도 이어붙이기.
                    # 조 > 항 > 호 > 목 순으로 한 단계 더 있고, 여기가 실제 최말단
                    # 내용인 경우가 많음(예: 의료법 제3조 "병원급 의료기관의 종류").
                    mokList = item.get("목", [])
                    if isinstance(mokList, dict):
                        mokList = [mokList]
                    for mok in mokList:
                        mokContent = str(mok.get("목내용", "")).strip()
                        if mokContent:
                            content += "\n" + mokContent

                fullContent = f"제{displayNo}조({title}) {j+1}항\n{content}".strip()
                docId = f"law_{mstId}_{artKey}_{clauseNo}"
                docs.append({
                    "_index": INDEX_NAME,
                    "_id":    docId,
                    "_source": {
                        "law_name":          lawName,
                        "law_mst_id":        mstId,
                        "sector":            sector,
                        "article_no":        displayNo,
                        "clause_no":         clauseNo,
                        "title":             title,
                        "content":           fullContent,
                        "content_hash":      hashContent(fullContent),
                        "effective_date":    effectiveDate,
                        "promulgation_date": promulgationDate,
                        "indexed_at":        datetime.now().isoformat(),
                    },
                })
    return docs


# ============================================================
# 변경 감지 (content_hash 비교) + 이력 스냅샷
# ============================================================

def diffAndSnapshot(osClient, dbConn, mstId, docs):
    """
    새로 파싱한 docs를 기존 OpenSearch 문서와 content_hash로 비교해서,
    실제로 바뀐(신규 포함) 문서만 골라낸다. 안 바뀐 문서는 건드리지 않아서
    knn_vector가 그대로 보존되고 불필요한 재임베딩을 피할 수 있다.
    바뀐/삭제된 문서는 law_article_history에 변경 전 내용을 스냅샷으로 남긴다.

    반환: (인덱싱 대상 docs 리스트, 변경 없어서 스킵한 개수)
    """
    newIds = [d["_id"] for d in docs]

    # STEP A: 기존 문서 mget으로 한 번에 조회 (law_mst_id + content_hash만 필요)
    existingById = {}
    if newIds:
        mgetResp = osClient.mget(
            index=INDEX_NAME,
            body={"ids": newIds},
            _source=["content", "content_hash", "article_no", "clause_no"],
        )
        for doc in mgetResp.get("docs", []):
            if doc.get("found"):
                existingById[doc["_id"]] = doc["_source"]

    # STEP B: 신규/변경만 남기고, 안 바뀐 건 스킵 + 바뀐 건 이력 스냅샷
    toIndex = []
    skipped = 0
    for d in docs:
        docId    = d["_id"]
        src      = d["_source"]
        existing = existingById.get(docId)

        if existing is None:
            recordLawHistory(
                dbConn, mstId, src["article_no"], src["clause_no"],
                oldContent=None, newContent=src["content"], changeType="added",
            )
            toIndex.append(d)
        elif existing.get("content_hash") != src["content_hash"]:
            recordLawHistory(
                dbConn, mstId, src["article_no"], src["clause_no"],
                oldContent=existing.get("content"), newContent=src["content"], changeType="modified",
            )
            toIndex.append(d)
        else:
            skipped += 1

    # STEP C: 이번 수집에서 사라진(삭제/폐지된) 조문 감지
    existingIdsResp = osClient.search(
        index=INDEX_NAME,
        body={
            "size":    10000,
            "_source": ["content", "article_no", "clause_no"],
            "query":   {"term": {"law_mst_id": mstId}},
        },
    )
    newIdSet = set(newIds)
    for hit in existingIdsResp["hits"]["hits"]:
        if hit["_id"] not in newIdSet:
            src = hit["_source"]
            recordLawHistory(
                dbConn, mstId, src["article_no"], src["clause_no"],
                oldContent=src["content"], newContent="", changeType="removed",
            )
            osClient.delete(index=INDEX_NAME, id=hit["_id"], ignore=[404])
            print(f"  [삭제 감지] {src['article_no']}조 {src['clause_no']}항 → law_article_history 기록 후 제거")

    return toIndex, skipped


# ============================================================
# 법령별 수집 실행
# ============================================================

def collectOneLaw(cfg, osClient, dbConn, mstId):
    """
    단일 법령(mstId) 수집 → 파싱 → 변경 감지 → OpenSearch 인덱싱 → PostgreSQL 기록.
    content_hash가 그대로인 조문은 재인덱싱하지 않아 knn_vector가 보존된다.
    반환: 인덱싱 성공 건수 (int)
    """
    lawInfo = LAW_MAP.get(mstId, {"name": mstId, "sector": "기타"})
    lawName = lawInfo['name']
    source  = f"law_{mstId}"
    print(f"\n[{lawName}] 수집 시작 (MST={mstId})")

    fetchedCount = 0
    indexedCount = 0
    try:
        # STEP A: API 호출
        lawData      = fetchLaw(cfg, mstId)
        docs         = parseClauses(lawData, mstId, lawInfo)
        fetchedCount = len(docs)
        print(f"  파싱된 조문(항) 수: {fetchedCount}")

        if fetchedCount == 0:
            print({"success": False, "message": f"{lawName}: 파싱된 조문 없음 - API 응답 구조 확인 필요"})
            recordLog(dbConn, source, "failed", error="파싱된 조문 없음")
            return 0

        # STEP B: 변경 감지 — 안 바뀐 조문은 인덱싱 대상에서 제외
        docsToIndex, skippedCount = diffAndSnapshot(osClient, dbConn, mstId, docs)
        print(f"  변경 없어 스킵: {skippedCount}건 / 신규·변경 인덱싱 대상: {len(docsToIndex)}건")

        if not docsToIndex:
            print("  변경된 조문 없음 — 인덱싱 생략")
            recordLog(dbConn, source, "success", fetched=fetchedCount, indexed=0,
                      error=None)
            updateLawMeta(dbConn, mstId, fetchedCount)
            return 0

        # STEP C: bulk 인덱싱 (신규·변경분만)
        successCount, errors = helpers.bulk(osClient, docsToIndex, raise_on_error=False)
        indexedCount = successCount
        if errors:
            print(f"  [WARN] 인덱싱 오류 {len(errors)}건: {errors[0]}")
        print(f"  인덱싱 완료: {indexedCount}건")

        # STEP D: 수집 이력 기록
        # doc_count는 "이번에 바뀐 건수"가 아니라 법령 전체 조문 수를 뜻하므로 fetchedCount 사용
        recordLog(dbConn, source, "success", fetched=fetchedCount, indexed=indexedCount)
        updateLawMeta(dbConn, mstId, fetchedCount)
        return indexedCount

    except Exception as e:
        print({"success": False, "message": f"{lawName} 수집 실패: {e}"})
        recordLog(dbConn, source, "failed", fetched=fetchedCount, error=str(e))
        return 0


# ============================================================
# 메인
# ============================================================

def main():
    """
    법령 수집 메인 함수.
    --mst 옵션으로 특정 법령만 수집하거나, 옵션 없이 전체 수집.
    """
    parser = argparse.ArgumentParser(description="법제처 법령 수집 → OpenSearch 인덱싱")
    parser.add_argument("--mst", help="특정 법령 MST ID만 수집 (예: --mst 259521)")
    args = parser.parse_args()

    # STEP 1: 설정 로드
    cfg = loadConfig()
    if not cfg['lawApiKey']:
        print({"success": False, "message": ".env에 LAW_API_KEY 가 없습니다."})
        sys.exit(1)

    # STEP 2: 클라이언트 초기화
    osClient = getOsClient(cfg)
    dbConn   = getDbConn(cfg)

    # STEP 3: 인덱스 확인/생성
    ensureIndex(osClient)

    # STEP 4: 수집 대상 결정
    if args.mst:
        if args.mst not in LAW_MAP:
            print({"success": False, "message": f"LAW_MAP에 없는 MST ID: {args.mst}"})
            sys.exit(1)
        targetList = [args.mst]
    else:
        targetList = list(LAW_MAP.keys())

    # STEP 5: 수집 실행
    totalIndexed = 0
    for i in range(0, len(targetList)):
        mstId         = targetList[i]
        totalIndexed += collectOneLaw(cfg, osClient, dbConn, mstId)

    # STEP 6: 종료
    dbConn.close()
    print(f"\n[완료] 총 인덱싱: {totalIndexed}건")


if __name__ == "__main__":
    main()
