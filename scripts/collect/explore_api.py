# -*- coding: utf-8 -*-
"""
explore_api.py
법제처 및 식약처 API 응답 필드 탐색 스크립트.

실행 결과를 data/raw/api_response_sample.txt에 저장하여
collect_law.py / collect_hazard.py 구현 전 필드 구조 확인에 사용.

사용법:
  python explore_api.py
"""

# ============================================================
# 라이브러리 임포트
# ============================================================

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))
from mazel_common import loadConfig, retryGet


# ============================================================
# 상수 정의
# ============================================================

LAW_API_BASE  = "https://www.law.go.kr/DRF/lawService.do"
HAZARD_RECALL     = "https://apis.data.go.kr/1471000/CsmtcsRtrvlSleStpgeInfo/getCsmtcsRtrvlSleStpgeInfo"
HAZARD_INGREDIENT = "https://apis.data.go.kr/1471000/CsmtcsUseRstrcInfoService/getCsmtcsUseRstrcInfoService"

LAW_MST_LIST = [
    {"name": "공중위생관리법", "mstId": "259521", "sector": "위생관리"},
    {"name": "화장품법",       "mstId": "270323", "sector": "화장품규제"},
    {"name": "의료법",         "mstId": "285327", "sector": "의료행위"},
]

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "raw", "api_response_sample.txt")


# ============================================================
# 탐색 함수
# ============================================================

def exploreLawApi(cfg, mstId, lawName):
    """
    법제처 API에서 법령 기본정보 + 조문 목록 응답을 가져와 필드 구조 출력.
    target=law 로 전체 법령 JSON 수신 (조문 포함).
    반환: 응답 원문(str)
    """
    params = {
        "OC":     cfg['lawApiKey'],
        "target": "law",
        "MST":    mstId,
        "type":   "JSON",
    }
    try:
        resp = retryGet(LAW_API_BASE, params=params)
        data = resp.json()
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"[ERROR] {lawName} (MST={mstId}): {e}"


def exploreHazardRecallApi(cfg):
    """
    식약처 화장품 회수·판매중지 정보 API 첫 페이지 샘플 응답을 가져와 필드 구조 출력.
    반환: 응답 원문(str)
    """
    params = {
        "serviceKey": cfg['publicApiKey'],
        "pageNo":     1,
        "numOfRows":  3,
        "type":       "json",
    }
    try:
        resp = retryGet(HAZARD_RECALL, params=params)
        data = resp.json()
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"[ERROR] hazard_recall: {e}"


def exploreHazardIngredientApi(cfg):
    """
    식약처 화장품 사용제한 원료정보 API 첫 페이지 샘플 응답을 가져와 필드 구조 출력.
    반환: 응답 원문(str)
    """
    params = {
        "serviceKey": cfg['publicApiKey'],
        "pageNo":     1,
        "numOfRows":  3,
        "type":       "json",
    }
    try:
        resp = retryGet(HAZARD_INGREDIENT, params=params)
        data = resp.json()
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"[ERROR] hazard_ingredient: {e}"


def printSection(title):
    """섹션 구분선 출력."""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


# ============================================================
# 메인
# ============================================================

def main():
    """
    API 탐색 메인 함수.
    각 API 응답 샘플을 콘솔 출력 후 data/raw/api_response_sample.txt 에 저장.
    """
    # STEP 1: 설정 로드
    cfg = loadConfig()
    if not cfg['lawApiKey']:
        print({"success": False, "message": ".env에 LAW_API_KEY 가 없습니다."})
        sys.exit(1)
    if not cfg['publicApiKey']:
        print({"success": False, "message": ".env에 PUBLIC_DATA_API_KEY 가 없습니다."})
        sys.exit(1)

    lines = []

    # STEP 2: 법제처 API 탐색 (3개 법령)
    printSection("[STEP 2] 법제처 API 탐색")
    for i in range(0, len(LAW_MST_LIST)):
        lawInfo = LAW_MST_LIST[i]
        header  = f"\n[법제처] {lawInfo['name']} (MST={lawInfo['mstId']})"
        print(header)
        result = exploreLawApi(cfg, lawInfo['mstId'], lawInfo['name'])
        preview = result[:800] + "\n...(truncated)" if len(result) > 800 else result
        print(preview)
        lines.append(header)
        lines.append(result)
        lines.append("")

    # STEP 3: 식약처 위해화장품 회수 API 탐색
    printSection("[STEP 3] 식약처 위해화장품 회수 API 탐색")
    header = "\n[식약처] 위해화장품 회수 정보"
    print(header)
    result = exploreHazardRecallApi(cfg)
    preview = result[:800] + "\n...(truncated)" if len(result) > 800 else result
    print(preview)
    lines.append(header)
    lines.append(result)
    lines.append("")

    # STEP 4: 식약처 화장품 사용제한 원료정보 API 탐색
    printSection("[STEP 4] 식약처 화장품 사용제한 원료정보 API 탐색")
    header = "\n[식약처] 화장품 사용제한 원료정보"
    print(header)
    result = exploreHazardIngredientApi(cfg)
    preview = result[:800] + "\n...(truncated)" if len(result) > 800 else result
    print(preview)
    lines.append(header)
    lines.append(result)
    lines.append("")

    # STEP 5: 결과 파일 저장
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n[STEP 5] 탐색 결과 저장 완료 → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
