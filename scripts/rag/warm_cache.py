# -*- coding: utf-8 -*-
"""
warm_cache.py
자주 나올 법한 질문(FAQ)을 미리 RAG 서버에 던져서 질문-답변 캐시(qa_cache.py)를
채워두는 워밍업 스크립트. 실제 사용자 요청과 동일하게 rag_server.py의
HTTP 엔드포인트를 호출하므로, 캐시 조회/적재 로직을 그대로 탄다.

전제: rag_server.py 가 이미 기동되어 있어야 함 (포트 5000).

사용법:
  python warm_cache.py                  # 기본 FAQ 목록 전체 실행
  python warm_cache.py --base-url http://localhost:5000
"""

# ============================================================
# 라이브러리 임포트
# ============================================================

import argparse
import time

import requests


# ============================================================
# FAQ 목록 — sector/apiType 별로 실사용자가 자주 물을 만한 질문
# ============================================================

LAW_FAQS = [
    # 위생관리 (30)
    {"query": "네일샵 개설하려면 어떤 신고가 필요한가요?",              "sector": "위생관리"},
    {"query": "피부관리사 자격증 없이 샵을 운영해도 되나요?",            "sector": "위생관리"},
    {"query": "이용업과 미용업의 차이가 뭔가요?",                        "sector": "위생관리"},
    {"query": "손 소독 안 하고 시술하면 처벌받나요?",                    "sector": "위생관리"},
    {"query": "1회용 시술 도구를 재사용해도 되나요?",                    "sector": "위생관리"},
    {"query": "수건을 손님마다 교체하지 않으면 처벌받나요?",              "sector": "위생관리"},
    {"query": "네일 기구 소독을 안 하면 어떤 제재를 받나요?",             "sector": "위생관리"},
    {"query": "속눈썹 연장샵을 개설하려면 어떤 신고가 필요한가요?",       "sector": "위생관리"},
    {"query": "왁싱 전문샵 운영에 필요한 자격증이 있나요?",               "sector": "위생관리"},
    {"query": "두피 케어샵도 미용업 신고 대상인가요?",                   "sector": "위생관리"},
    {"query": "발마사지샵을 개설하려면 어떤 절차가 필요한가요?",          "sector": "위생관리"},
    {"query": "반영구화장샵도 위생관리법 적용을 받나요?",                 "sector": "위생관리"},
    {"query": "타투샵을 운영하려면 어떤 신고가 필요한가요?",              "sector": "위생관리"},
    {"query": "무자격자가 미용 시술을 하면 어떤 처벌을 받나요?",          "sector": "위생관리"},
    {"query": "자격증을 대여해서 샵을 운영해도 되나요?",                  "sector": "위생관리"},
    {"query": "미용사 면허가 취소되는 경우는 어떤 게 있나요?",            "sector": "위생관리"},
    {"query": "영업소를 이전할 때 신고가 필요한가요?",                    "sector": "위생관리"},
    {"query": "샵 명의를 변경하려면 어떻게 해야 하나요?",                 "sector": "위생관리"},
    {"query": "휴업 신고를 안 하고 장기간 문을 닫아도 되나요?",           "sector": "위생관리"},
    {"query": "폐업 신고 절차가 어떻게 되나요?",                         "sector": "위생관리"},
    {"query": "위생교육을 안 받으면 어떤 불이익이 있나요?",               "sector": "위생관리"},
    {"query": "영업정지 처분 기준이 어떻게 되나요?",                     "sector": "위생관리"},
    {"query": "위생관리법 위반 시 과태료는 얼마나 부과되나요?",           "sector": "위생관리"},
    {"query": "환기 시설이 없으면 위생기준 위반인가요?",                  "sector": "위생관리"},
    {"query": "폐기물(솜, 니들 등) 처리는 어떻게 해야 하나요?",           "sector": "위생관리"},
    {"query": "프랜차이즈로 샵을 여러 개 운영해도 되나요?",               "sector": "위생관리"},
    {"query": "미용업과 세탁업을 겸업할 수 있나요?",                     "sector": "위생관리"},
    {"query": "종사자 건강진단서를 제출하지 않으면 처벌받나요?",          "sector": "위생관리"},
    {"query": "영업신고증을 게시하지 않으면 처벌받나요?",                 "sector": "위생관리"},
    {"query": "출장 미용 서비스도 신고 대상인가요?",                     "sector": "위생관리"},

    # 화장품규제 (30)
    {"query": "화장품 광고에 '주름 개선'이라고 써도 되나요?",            "sector": "화장품규제"},
    {"query": "수제 화장품을 만들어서 판매해도 되나요?",                 "sector": "화장품규제"},
    {"query": "화장품 성분표를 표시 안 하면 어떻게 되나요?",             "sector": "화장품규제"},
    {"query": "화장품에 '미백 효과'라고 광고해도 되나요?",               "sector": "화장품규제"},
    {"query": "여드름 치료 효과가 있다고 광고해도 되나요?",              "sector": "화장품규제"},
    {"query": "아토피 개선 효과를 표방해도 되나요?",                    "sector": "화장품규제"},
    {"query": "자외선 차단 효과를 과장해서 광고하면 어떻게 되나요?",      "sector": "화장품규제"},
    {"query": "리프팅 효과가 있다고 광고해도 되나요?",                   "sector": "화장품규제"},
    {"query": "피부 재생 효과를 표시해도 되나요?",                       "sector": "화장품규제"},
    {"query": "탈모 방지 효과가 있다고 광고해도 되나요?",                "sector": "화장품규제"},
    {"query": "화장품을 소분해서 판매해도 되나요?",                     "sector": "화장품규제"},
    {"query": "맞춤형 화장품 판매업 신고가 필요한가요?",                 "sector": "화장품규제"},
    {"query": "해외 직구 화장품을 매장에서 팔아도 되나요?",              "sector": "화장품규제"},
    {"query": "화장품 제조업 등록 없이 자체 제작해서 팔아도 되나요?",     "sector": "화장품규제"},
    {"query": "화장품 유통기한을 표시하지 않으면 처벌받나요?",           "sector": "화장품규제"},
    {"query": "제조번호를 표시하지 않은 화장품을 팔아도 되나요?",         "sector": "화장품규제"},
    {"query": "화장품 품질검사를 안 받고 판매해도 되나요?",              "sector": "화장품규제"},
    {"query": "OEM 화장품을 자체 브랜드로 판매해도 되나요?",             "sector": "화장품규제"},
    {"query": "동물실험을 한 화장품 원료를 써도 되나요?",                "sector": "화장품규제"},
    {"query": "알레르기 유발 성분을 표시하지 않아도 되나요?",            "sector": "화장품규제"},
    {"query": "사용제한 원료 기준을 초과해서 사용하면 어떻게 되나요?",    "sector": "화장품규제"},
    {"query": "금지된 원료가 검출되면 어떤 처벌을 받나요?",              "sector": "화장품규제"},
    {"query": "화장품 안전성 평가를 받지 않아도 되나요?",                "sector": "화장품규제"},
    {"query": "화장품 부작용을 보고하지 않으면 처벌받나요?",             "sector": "화장품규제"},
    {"query": "화장품 회수 명령을 어기면 어떻게 되나요?",                "sector": "화장품규제"},
    {"query": "표시광고 심의를 받지 않고 광고해도 되나요?",              "sector": "화장품규제"},
    {"query": "기능성 화장품 심사를 받지 않고 판매해도 되나요?",         "sector": "화장품규제"},
    {"query": "화장품책임판매업 등록 없이 수입 화장품을 팔아도 되나요?",  "sector": "화장품규제"},
    {"query": "성분표시를 영문으로만 표기해도 되나요?",                  "sector": "화장품규제"},
    {"query": "화장품 용기에 안전 경고문구를 표시하지 않아도 되나요?",    "sector": "화장품규제"},

    # 의료행위 (20)
    {"query": "왁싱은 의료행위에 해당하나요?",                          "sector": "의료행위"},
    {"query": "속눈썹 연장 시술이 불법인가요?",                         "sector": "의료행위"},
    {"query": "반영구 화장(타투)은 에스테틱 샵에서 해도 되나요?",        "sector": "의료행위"},
    {"query": "피어싱 시술은 에스테틱 샵에서 해도 되나요?",              "sector": "의료행위"},
    {"query": "화학 필링(박피) 시술은 의료행위인가요?",                  "sector": "의료행위"},
    {"query": "고주파 리프팅 기기 시술은 에스테틱 샵에서 해도 되나요?",   "sector": "의료행위"},
    {"query": "레이저 제모는 에스테틱 샵에서 해도 되나요?",              "sector": "의료행위"},
    {"query": "미세침(더모롤러) 시술은 의료행위에 해당하나요?",          "sector": "의료행위"},
    {"query": "얼굴 각질 제거 스크래치 시술은 괜찮나요?",                "sector": "의료행위"},
    {"query": "무면허 의료행위를 하면 어떤 처벌을 받나요?",              "sector": "의료행위"},
    {"query": "간호사가 에스테틱 샵에서 시술해도 되나요?",               "sector": "의료행위"},
    {"query": "의료기기를 에스테틱 샵에서 사용해도 되나요?",             "sector": "의료행위"},
    {"query": "마취 크림을 시술 전에 발라줘도 되나요?",                  "sector": "의료행위"},
    {"query": "필러나 보톡스 시술을 에스테틱 샵에서 해도 되나요?",       "sector": "의료행위"},
    {"query": "문신(타투)은 의료행위로 분류되나요?",                    "sector": "의료행위"},
    {"query": "침 시술을 에스테틱 샵에서 해도 되나요?",                  "sector": "의료행위"},
    {"query": "부항 시술은 에스테틱 샵에서 해도 되나요?",                "sector": "의료행위"},
    {"query": "카이로프랙틱 시술은 에스테틱 샵에서 해도 되나요?",        "sector": "의료행위"},
    {"query": "귀 피어싱은 의료인만 할 수 있나요?",                      "sector": "의료행위"},
    {"query": "속눈썹 펌은 의료행위에 해당하지 않나요?",                 "sector": "의료행위"},

    # sector 미지정 — 전체 검색 (10)
    {"query": "인스타에 여드름 치료 전문샵이라고 써도 되나요?",          "sector": None},
    {"query": "에스테틱 샵에서 하면 안 되는 시술은 뭐가 있나요?",        "sector": None},
    {"query": "마케팅 문구로 '의학적으로 검증된'이라고 써도 되나요?",     "sector": None},
    {"query": "샵 간판에 '피부과 부럽지 않은'이라고 써도 되나요?",       "sector": None},
    {"query": "고객 후기에 시술 효과를 과장해서 올려도 되나요?",         "sector": None},
    {"query": "체험단 이벤트로 시술 전후 사진을 올려도 되나요?",         "sector": None},
    {"query": "블로그에 '전문의 추천'이라고 써도 되나요?",              "sector": None},
    {"query": "당근마켓에 시술 홍보 글을 올려도 되나요?",                "sector": None},
    {"query": "샵 이름에 '클리닉'이라는 단어를 써도 되나요?",            "sector": None},
    {"query": "가격 할인 이벤트 문구에 제한이 있나요?",                  "sector": None},
]

HAZARD_FAQS = [
    {"query": "파라벤이 함유된 화장품 사용해도 안전한가요?"},
    {"query": "회수 조치된 화장품 목록을 확인할 수 있나요?"},
    {"query": "메탄올이 검출된 화장품 회수 사례가 있나요?"},
    {"query": "사용제한 원료 기준을 초과한 성분이 있나요?"},
    {"query": "벤젠이 검출된 화장품 회수 사례가 있나요?"},
    {"query": "포름알데히드가 함유된 제품이 회수된 적 있나요?"},
    {"query": "하이드로퀴논은 화장품에 사용해도 되나요?"},
    {"query": "스테로이드 성분이 검출된 화장품 사례가 있나요?"},
    {"query": "중금속이 검출된 화장품 회수 사례가 있나요?"},
    {"query": "미생물 기준을 초과한 화장품이 회수된 적 있나요?"},
]


# ============================================================
# 워밍업 실행
# ============================================================

def warmLawFaqs(baseUrl):
    """법령 FAQ를 /rag/query 로 순차 호출."""
    for i in range(0, len(LAW_FAQS)):
        item  = LAW_FAQS[i]
        start = time.time()
        try:
            resp = requests.post(
                f"{baseUrl}/rag/query",
                json={"query": item["query"], "sector": item["sector"], "topk": 5},
                timeout=120,
            )
            resp.raise_for_status()
            elapsed = time.time() - start
            print(f"  [{i+1}/{len(LAW_FAQS)}] ({elapsed:5.1f}s) {item['query']}")
        except Exception as e:
            print(f"  [{i+1}/{len(LAW_FAQS)}] 실패: {item['query']} — {e}")


def warmHazardFaqs(baseUrl):
    """안전 정보 FAQ를 /rag/query 로 순차 호출 (runCombinedRag가 hazard 검색을 자동 포함)."""
    for i in range(0, len(HAZARD_FAQS)):
        item  = HAZARD_FAQS[i]
        start = time.time()
        try:
            resp = requests.post(
                f"{baseUrl}/rag/query",
                json={"query": item["query"], "sector": None, "topk": 5},
                timeout=120,
            )
            resp.raise_for_status()
            elapsed = time.time() - start
            print(f"  [{i+1}/{len(HAZARD_FAQS)}] ({elapsed:5.1f}s) {item['query']}")
        except Exception as e:
            print(f"  [{i+1}/{len(HAZARD_FAQS)}] 실패: {item['query']} — {e}")


# ============================================================
# 메인
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="RAG 질문-답변 캐시 워밍업")
    parser.add_argument("--base-url", default="http://localhost:5000",
                        help="rag_server.py 주소 (기본: http://localhost:5000)")
    args = parser.parse_args()

    print(f"[법령 FAQ 워밍업] {len(LAW_FAQS)}건")
    warmLawFaqs(args.base_url)

    print(f"\n[안전정보 FAQ 워밍업] {len(HAZARD_FAQS)}건")
    warmHazardFaqs(args.base_url)

    print("\n[완료] 캐시 워밍업 종료")


if __name__ == "__main__":
    main()
