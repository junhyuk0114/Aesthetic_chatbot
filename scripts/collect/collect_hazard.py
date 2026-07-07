# -*- coding: utf-8 -*-
"""
collect_hazard.py
식약처 API에서 화장품 회수·판매중지 정보 및 사용제한 원료정보를 수집하여
OpenSearch hazard-products 인덱스에 적재.
PostgreSQL collection_log / hazard_sync_meta 에 수집 이력 기록.

사용제한 원료정보(ingredient)는 국가(COUNTRY_NAME) 필드가 "한국"이거나
비어있는(누락된) 항목만 수집한다. 해외 전용 규제(EU/중국/일본 등)는
제외 — isDomesticIngredient() 참고.

사용법:
  python collect_hazard.py                  # 회수 + 원료제한 전체 수집
  python collect_hazard.py --type recall     # 회수·판매중지 정보만 수집
  python collect_hazard.py --type ingredient # 사용제한 원료정보만 수집
"""

# ============================================================
# 라이브러리 임포트
# ============================================================

import argparse
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))
from mazel_common import loadConfig, retryGet, getOsClient, getDbConn, recordLog, updateHazardMeta
from opensearchpy import helpers


# ============================================================
# 상수 정의
# ============================================================

INDEX_NAME     = "hazard-products"
PAGE_SIZE      = 500   # data.go.kr numOfRows 최대값
PAGE_SLEEP_SEC = 0.3   # 페이지 간 호출 간격 (Rate Limit/일시 차단 방지)

API_MAP = {
    "recall": {
        "url":    "https://apis.data.go.kr/1471000/CsmtcsRtrvlSleStpgeInfo/getCsmtcsRtrvlSleStpgeInfo",
        "label":  "화장품 회수·판매중지 정보",
        "sector": "위해화장품",
    },
    "ingredient": {
        "url":    "https://apis.data.go.kr/1471000/CsmtcsUseRstrcInfoService/getCsmtcsUseRstrcInfoService",
        "label":  "화장품 사용제한 원료정보",
        "sector": "사용제한원료",
    },
}


# ============================================================
# OpenSearch 인덱스 생성
# ============================================================

def ensureIndex(osClient):
    """
    hazard-products 인덱스가 없으면 생성.
    회수·판매중지(제품 단위) / 사용제한 원료(성분 단위) 두 유형을
    하나의 인덱스에서 관리하는 슈퍼셋 스키마.
    knn_vector 필드(1024차원)는 embed_index.py에서 채워짐.
    """
    if osClient.indices.exists(index=INDEX_NAME):
        return

    mapping = {
        "settings": {
            "number_of_shards":   1,
            "number_of_replicas": 0,
            "index.knn":          True,
        },
        "mappings": {
            "properties": {
                "api_type":            {"type": "keyword"},
                "sector":              {"type": "keyword"},
                # 회수·판매중지 (product) 필드
                "product_name":        {"type": "text",    "analyzer": "standard"},
                "company_name":        {"type": "keyword"},
                "biz_reg_no":          {"type": "keyword"},
                # 사용제한 원료 (ingredient) 필드
                "ingredient_name":     {"type": "text",    "analyzer": "standard"},
                "ingredient_eng_name": {"type": "keyword"},
                "cas_no":              {"type": "keyword"},
                "country_name":        {"type": "keyword"},
                "regulate_type":       {"type": "keyword"},
                # 공통
                "hazard_detail":       {"type": "text",    "analyzer": "standard"},
                "report_date":         {"type": "date",    "format": "yyyyMMdd||yyyy-MM-dd"},
                "recall_end_date":     {"type": "date",    "format": "yyyyMMdd||yyyy-MM-dd"},
                "content":             {"type": "text",    "analyzer": "standard"},
                "raw_json":            {"type": "object",  "enabled": False},
                "indexed_at":          {"type": "date"},
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
# 페이지 수집
# ============================================================

def fetchPage(cfg, url, pageNo):
    """
    식약처 API 단일 페이지 수신.
    반환: (items 리스트, totalCount int)
    """
    params = {
        "serviceKey": cfg['publicApiKey'],
        "type":       "json",
        "numOfRows":  PAGE_SIZE,
        "pageNo":     pageNo,
    }
    resp       = retryGet(url, params=params)
    data       = resp.json()
    body       = data.get("body", {})
    items      = body.get("items", []) or []
    totalCount = int(body.get("totalCount", 0))
    return items, totalCount


# ============================================================
# 문서 파싱
# ============================================================

def parseDate(rawDate):
    """
    날짜 문자열을 yyyyMMdd 형태로 정규화. 누락 시 None 반환.
    """
    if not rawDate:
        return None
    cleaned = str(rawDate).strip().replace("-", "").replace(".", "")
    if len(cleaned) == 8 and cleaned.isdigit():
        return cleaned
    return None


def isDomesticIngredient(countryName):
    """
    사용제한 원료(ingredient) 항목의 국가(COUNTRY_NAME → country_name) 필드가
    "한국"이거나 비어있으면(응답에 국가 정보가 누락된 경우) True.
    해외 전용 규제(EU/중국/일본/아세안 등)만 False로 걸러냄 — 국가 필드가
    비어있는 항목은 실수로 누락되지 않도록 항상 포함시킨다.
    """
    return countryName == "" or countryName == "한국"


def parseRecallItem(item, globalIdx):
    """
    화장품 회수·판매중지 정보 응답 항목 → OpenSearch 문서.
    (CsmtcsRtrvlSleStpgeInfo 실응답 필드 기준: ENTP_NAME, ITEM_NAME, DISPS_CONT,
     RECALL_COMMAND_DATE, OPEN_END_DATE, BIZRNO)
    """
    productName   = str(item.get("ITEM_NAME",            "")).strip()
    companyName   = str(item.get("ENTP_NAME",             "")).strip()
    dispsCont     = str(item.get("DISPS_CONT",            "")).strip()
    bizNo         = str(item.get("BIZRNO",                "")).strip()
    reportDate    = parseDate(item.get("RECALL_COMMAND_DATE", ""))
    recallEndDate = parseDate(item.get("OPEN_END_DATE",       ""))

    content = f"[위해화장품 회수·판매중지] {productName} | 업체: {companyName} | 사유: {dispsCont}"
    return {
        "_index": INDEX_NAME,
        "_id":    f"hazard_recall_{globalIdx}",
        "_source": {
            "api_type":        "recall",
            "sector":          "위해화장품",
            "product_name":    productName,
            "company_name":    companyName,
            "biz_reg_no":      bizNo,
            "hazard_detail":   dispsCont,
            "report_date":     reportDate,
            "recall_end_date": recallEndDate,
            "content":         content,
            "raw_json":        item,
            "indexed_at":      datetime.now().isoformat(),
        },
    }


def parseIngredientItem(item, globalIdx):
    """
    화장품 사용제한 원료정보 응답 항목 → OpenSearch 문서.
    (CsmtcsUseRstrcInfoService 실응답 필드 기준: REGULATE_TYPE, INGR_STD_NAME,
     INGR_ENG_NAME, CAS_NO, COUNTRY_NAME, NOTICE_INGR_NAME, LIMIT_COND)
    """
    ingredientName    = str(item.get("INGR_STD_NAME",  "")).strip()
    ingredientEngName = str(item.get("INGR_ENG_NAME",  "")).strip()
    casNo             = str(item.get("CAS_NO",         "")).strip()
    countryName       = str(item.get("COUNTRY_NAME",   "")).strip()
    regulateType      = str(item.get("REGULATE_TYPE",  "")).strip()
    limitCond         = str(item.get("LIMIT_COND") or "").strip()

    detail  = f"{regulateType} 성분 ({countryName})"
    if limitCond:
        detail += f" | 제한조건: {limitCond}"

    content = f"[화장품 사용제한 원료] {ingredientName}({ingredientEngName}) | 구분: {regulateType} | 국가: {countryName}"
    if limitCond:
        content += f" | 제한조건: {limitCond}"

    return {
        "_index": INDEX_NAME,
        "_id":    f"hazard_ingredient_{globalIdx}",
        "_source": {
            "api_type":            "ingredient",
            "sector":              "사용제한원료",
            "ingredient_name":     ingredientName,
            "ingredient_eng_name": ingredientEngName,
            "cas_no":              casNo,
            "country_name":        countryName,
            "regulate_type":       regulateType,
            "hazard_detail":       detail,
            "content":             content,
            "raw_json":            item,
            "indexed_at":          datetime.now().isoformat(),
        },
    }


# ============================================================
# API 타입별 수집 실행
# ============================================================

def collectOneType(cfg, osClient, dbConn, apiType):
    """
    단일 API 타입(recall|ingredient) 전체 페이지 수집 → 인덱싱 → 기록.
    반환: 인덱싱 성공 건수 (int)
    """
    apiInfo  = API_MAP[apiType]
    url      = apiInfo['url']
    label    = apiInfo['label']
    source   = f"hazard_{apiType}"
    parseFn  = parseRecallItem if apiType == "recall" else parseIngredientItem

    print(f"\n[{label}] 수집 시작")

    allDocs   = []
    rawCount  = 0   # API가 실제로 반환한 원본 항목 수 (필터 적용 전, 페이징 종료 판단용)
    pageNo    = 1

    try:
        # STEP A: 전체 페이지 순회 수집
        while True:
            items, totalCount = fetchPage(cfg, url, pageNo)
            if not items:
                break

            for i in range(0, len(items)):
                globalIdx = (pageNo - 1) * PAGE_SIZE + i
                doc       = parseFn(items[i], globalIdx)
                if apiType == "ingredient" and not isDomesticIngredient(doc["_source"]["country_name"]):
                    continue   # 해외 전용 규제(국가 필드가 "한국"도 아니고 비어있지도 않음)는 제외
                allDocs.append(doc)

            rawCount = (pageNo - 1) * PAGE_SIZE + len(items)
            print(f"  페이지 {pageNo} 완료 (원본 {rawCount}/{totalCount}건, 국내 필터 후 {len(allDocs)}건)")

            if rawCount >= totalCount:
                break
            pageNo += 1
            time.sleep(PAGE_SLEEP_SEC)

        if rawCount == 0:
            print({"success": False, "message": f"{label}: 수집된 항목 없음 - API 키 또는 URL 확인 필요"})
            recordLog(dbConn, source, "failed", error="수집 항목 없음")
            return 0

        # STEP B: bulk 인덱싱 (필터링된 문서만)
        successCount, errors = helpers.bulk(osClient, allDocs, raise_on_error=False)
        if errors:
            print(f"  [WARN] 인덱싱 오류 {len(errors)}건: {errors[0]}")
        print(f"  인덱싱 완료: {successCount}건 (원본 수집 {rawCount}건 중 국내/미상 필터 후)")

        # STEP C: 수집 이력 기록 (fetched=원본 API 수신량, indexed=필터 후 실제 색인량)
        recordLog(dbConn, source, "success", fetched=rawCount, indexed=successCount)
        updateHazardMeta(dbConn, apiType, successCount)
        return successCount

    except Exception as e:
        print({"success": False, "message": f"{label} 수집 실패: {e}"})
        recordLog(dbConn, source, "failed", fetched=rawCount, error=str(e))
        return 0


# ============================================================
# 메인
# ============================================================

def main():
    """
    위해상품(회수·판매중지) 및 사용제한 원료정보 수집 메인 함수.
    --type 옵션으로 타입 지정하거나, 옵션 없이 전체(recall+ingredient) 수집.
    """
    parser = argparse.ArgumentParser(description="식약처 위해상품·사용제한원료 수집 → OpenSearch 인덱싱")
    parser.add_argument("--type", choices=["recall", "ingredient"],
                        help="특정 API 타입만 수집 (recall: 회수·판매중지 / ingredient: 사용제한 원료)")
    args = parser.parse_args()

    # STEP 1: 설정 로드
    cfg = loadConfig()
    if not cfg['publicApiKey']:
        print({"success": False, "message": ".env에 PUBLIC_DATA_API_KEY 가 없습니다."})
        sys.exit(1)

    # STEP 2: 클라이언트 초기화
    osClient = getOsClient(cfg)
    dbConn   = getDbConn(cfg)

    # STEP 3: 인덱스 확인/생성
    ensureIndex(osClient)

    # STEP 4: 수집 대상 결정
    if args.type:
        targetList = [args.type]
    else:
        targetList = list(API_MAP.keys())

    # STEP 5: 수집 실행
    totalIndexed = 0
    for i in range(0, len(targetList)):
        apiType       = targetList[i]
        totalIndexed += collectOneType(cfg, osClient, dbConn, apiType)

    # STEP 6: 종료
    dbConn.close()
    print(f"\n[완료] 총 인덱싱: {totalIndexed}건")


if __name__ == "__main__":
    main()
