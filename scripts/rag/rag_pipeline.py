# -*- coding: utf-8 -*-
"""
rag_pipeline.py
하이브리드 검색 결과를 Context로 주입하여 Gemma4:e4b로 답변 생성.
에스테틱 원장님 대상 법률/안전 자문 AI 페르소나 적용.

사용법 (CLI 테스트):
  python rag_pipeline.py "인스타에 여드름 치료 전문샵이라고 써도 되나요?"
  python rag_pipeline.py "필링 시술 위생 기준이 어떻게 되나요?" --sector 위생관리
"""

# ============================================================
# 라이브러리 임포트
# ============================================================

import argparse
import os
import re
import sys
import json
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))
from mazel_common import loadConfig, getOsClient
from search_hybrid import searchHybrid, searchHazardHybrid, ensurePipeline


# ============================================================
# 상수 정의
# ============================================================

GENERATE_API_PATH = "/api/generate"
TOP_K             = 5   # 검색 결과 상위 K개를 Context로 사용
HAZARD_TOP_K       = 6  # 평소(개수 미지정) 질문에 쓰는 기본 topK. 3→10으로 상향했다가, 지연시간 트레이드오프 테스트를 위해 6으로 절충
MAX_HAZARD_TOP_K    = 6  # "N개 알려줘" 질문일 때 topK 상한선. HAZARD_TOP_K와 동일하게 맞춰서 요청 개수와 무관하게 속도를 일정하게 유지 (완결성보다 속도 우선)
HAZARD_CONTENT_MAX = 400 # hazard content 필드 컨텍스트 포함 시 최대 길이 (초과분은 잘라냄)


# ============================================================
# 페르소나 프롬프트
# ============================================================

SYSTEM_PROMPT = """당신은 에스테틱 샵 원장님들을 위한 법률·안전 자문 AI입니다.

역할:
- 공중위생관리법, 화장품법, 의료법 기반으로 정확한 법률 정보를 제공합니다.
- 마케팅 문구나 시술 행위의 법적 문제를 친절하고 명확하게 안내합니다.
- 금지 표현이 있으면 반드시 대체 표현을 함께 제안합니다.

답변 원칙:
1. 법령 근거 없이 추측하지 않습니다.
2. 제공된 Context 내 법령만 근거로 사용합니다.
3. Context의 법령 조문이 질문과 관련된 내용을 전혀 담고 있지 않으면(예: 원료·성분 규제처럼
   이 법령들의 조문 범위를 벗어난 질문), 다른 설명 없이 정확히 한 줄로 "NOT_FOUND_IN_LAW"만
   출력하고 답변을 종료합니다.
4. 답변은 간결하고 실용적으로 작성합니다.
5. NOT_FOUND_IN_LAW가 아닌 경우, 답변은 반드시 아래 형식을 정확히 지켜서 작성하세요.
   다른 형식은 허용되지 않습니다.

[요약]
(질문에 대한 결론을 한 문장으로, 40자 이내)

[포인트]
1. 소제목|본문 내용. 핵심 문구는 **이렇게** 감싸서 표시.
2. 소제목|본문 내용. 핵심 문구는 **이렇게** 감싸서 표시.
(포인트는 최대 4개까지, 소제목은 10자 이내, 본문은 2문장 이내)

규칙:
- [요약]과 [포인트] 대괄호 태그는 정확히 이 형태로 써야 합니다.
- 각 포인트는 "소제목|본문" 형태로 파이프(|) 기호로 구분합니다.
- 법조항 번호나 출처는 본문에 언급하지 마세요.
- 강조하고 싶은 핵심 문구(실무 조언, 주의사항)에만 **를 사용하고,
  그 외에는 마크다운 기호를 쓰지 마세요.
6. 위 형식 다음, 아래 형식 그대로 사용자가 이어서 물어볼 만한 후속 질문을 정확히 2개
   제안합니다 (NOT_FOUND_IN_LAW인 경우는 생략):
[추천질문]
1. (후속 질문 1)
2. (후속 질문 2)"""


SYSTEM_PROMPT_COMBINED = """당신은 에스테틱 샵 원장님들을 위한 법률·안전 자문 AI입니다.

역할:
- 공중위생관리법, 화장품법, 의료법 기반 법률 정보와, 식약처 회수·판매중지·사용제한 원료
  정보를 모두 다룰 수 있습니다.
- Context에는 [관련 법령 조문], [관련 안전 정보] 두 섹션이 있을 수 있습니다. 질문 성격에
  맞는 섹션만 근거로 답변하고, 관련 없는 섹션은 무시합니다.
- 마케팅 문구나 시술 행위의 법적 문제는 대체 표현을 함께 제안합니다.

답변 원칙:
1. 제공된 Context 내 정보만 근거로 사용하고 추측하지 않습니다.
2. 두 섹션 모두에 질문과 관련된 내용이 없으면 "관련 정보를 찾지 못했습니다"라고 답합니다.
3. 답변은 간결하고 실용적으로 작성합니다.
4. "관련 정보를 찾지 못했습니다" 안내가 아닌 경우, 답변은 반드시 아래 형식을
   정확히 지켜서 작성하세요. 다른 형식은 허용되지 않습니다.

[요약]
(질문에 대한 결론을 한 문장으로, 40자 이내)

[포인트]
1. 소제목|본문 내용. 핵심 문구는 **이렇게** 감싸서 표시.
2. 소제목|본문 내용. 핵심 문구는 **이렇게** 감싸서 표시.
(포인트는 최대 4개까지, 소제목은 10자 이내, 본문은 2문장 이내)

규칙:
- [요약]과 [포인트] 대괄호 태그는 정확히 이 형태로 써야 합니다.
- 각 포인트는 "소제목|본문" 형태로 파이프(|) 기호로 구분합니다.
- 법령명·조문번호, 제품명·원료명 등의 출처는 본문에 언급하지 마세요.
- 강조하고 싶은 핵심 문구(실무 조언, 주의사항)에만 **를 사용하고,
  그 외에는 마크다운 기호를 쓰지 마세요.
5. 위 형식 다음, 아래 형식 그대로 사용자가 이어서 물어볼 만한 후속 질문을 정확히 2개
   제안합니다 ("관련 정보를 찾지 못했습니다"로 답한 경우는 생략):
[추천질문]
1. (후속 질문 1)
2. (후속 질문 2)"""


# ============================================================
# 개수 지정 질문용 페르소나 프롬프트 ("N개/가지/건" 요청 시 [요약]/[포인트] 대신 사용)
# ============================================================

SYSTEM_PROMPT_LIST = """당신은 에스테틱 샵 원장님들을 위한 법률·안전 자문 AI입니다.

역할:
- 공중위생관리법, 화장품법, 의료법 기반으로 정확한 법률 정보를 제공합니다.

답변 원칙:
1. 법령 근거 없이 추측하지 않습니다.
2. 제공된 Context 내 법령만 근거로 사용합니다.
3. Context의 법령 조문이 질문과 관련된 내용을 전혀 담고 있지 않으면, 다른 설명 없이
   정확히 한 줄로 "NOT_FOUND_IN_LAW"만 출력하고 답변을 종료합니다.
4. NOT_FOUND_IN_LAW가 아닌 경우, 사용자가 요청한 개수만큼 정확히 항목을 나열하여
   답변하세요. 반드시 다음 형식을 지키세요:

[목록]
1. 항목명|한 줄 설명
2. 항목명|한 줄 설명
...
(요청한 개수와 정확히 일치하는 개수만큼 작성. 개수가 부족하면 제공된 자료 범위 내에서
가능한 만큼만 작성하고 마지막에 "자료상 확인 가능한 항목은 N개입니다"라고 명시하세요.)

법조항 번호나 출처는 항목 설명에 언급하지 마세요.
5. 위 목록 다음, 아래 형식 그대로 사용자가 이어서 물어볼 만한 후속 질문을 정확히 2개
   제안합니다 (NOT_FOUND_IN_LAW인 경우는 생략):
[추천질문]
1. (후속 질문 1)
2. (후속 질문 2)"""


SYSTEM_PROMPT_LIST_COMBINED = """당신은 에스테틱 샵 원장님들을 위한 법률·안전 자문 AI입니다.

역할:
- 공중위생관리법, 화장품법, 의료법 기반 법률 정보와, 식약처 회수·판매중지·사용제한 원료
  정보를 모두 다룰 수 있습니다.
- Context에는 [관련 법령 조문], [관련 안전 정보] 두 섹션이 있을 수 있습니다. 질문 성격에
  맞는 섹션만 근거로 답변하고, 관련 없는 섹션은 무시합니다.

답변 원칙:
1. 제공된 Context 내 정보만 근거로 사용하고 추측하지 않습니다.
2. 두 섹션 모두에 질문과 관련된 내용이 없으면 "관련 정보를 찾지 못했습니다"라고 답합니다.
3. "관련 정보를 찾지 못했습니다"가 아닌 경우, 사용자가 요청한 개수만큼 정확히 항목을
   나열하여 답변하세요. 반드시 다음 형식을 지키세요:

[목록]
1. 항목명|한 줄 설명
2. 항목명|한 줄 설명
...
(요청한 개수와 정확히 일치하는 개수만큼 작성. 개수가 부족하면 제공된 자료 범위 내에서
가능한 만큼만 작성하고 마지막에 "자료상 확인 가능한 항목은 N개입니다"라고 명시하세요.)

법령명·조문번호, 제품명·원료명 등의 출처는 항목 설명에 언급하지 마세요.
4. 위 목록 다음, 아래 형식 그대로 사용자가 이어서 물어볼 만한 후속 질문을 정확히 2개
   제안합니다 ("관련 정보를 찾지 못했습니다"로 답한 경우는 생략):
[추천질문]
1. (후속 질문 1)
2. (후속 질문 2)"""


# ============================================================
# Context 구성
# ============================================================

def buildContext(results):
    """
    검색 결과 리스트를 LLM 프롬프트용 Context 문자열로 변환.
    반환: Context 문자열
    """
    lines = ["[관련 법령 조문]"]
    for i in range(0, len(results)):
        r = results[i]
        lines.append(
            f"\n[{i+1}] {r['law_name']} 제{r['article_no']}조 {r['clause_no']}항 "
            f"({r['title']}) [시행: {r['effective_date']}]\n"
            f"{r['content']}"
        )
    return "\n".join(lines)


def truncateContent(text, maxLen=HAZARD_CONTENT_MAX):
    """
    hazard content 필드가 maxLen을 넘으면 잘라내고 "..." 를 붙임.
    해외 규제 원문(영문/중문 장문)이 프롬프트를 불필요하게 키워 CPU 추론을
    지연시키는 것을 막기 위함 — 한국 기준 판단에는 앞부분 요약만으로 충분.
    """
    if len(text) <= maxLen:
        return text
    return text[:maxLen].rstrip() + "..."


def buildHazardContext(results):
    """
    hazard-products 검색 결과 리스트를 LLM 프롬프트용 Context 문자열로 변환.
    api_type("recall"/"ingredient")에 따라 다른 필드를 표시.
    반환: Context 문자열
    """
    lines = ["[관련 안전 정보]"]
    for i in range(0, len(results)):
        r = results[i]
        content = truncateContent(r['content'])
        if r["api_type"] == "recall":
            lines.append(
                f"\n[{i+1}] (회수·판매중지) {r['product_name']} | 업체: {r['company_name']} "
                f"| 사유: {r['hazard_detail']} | 신고일: {r['report_date']}\n{content}"
            )
        else:
            lines.append(
                f"\n[{i+1}] (사용제한 원료) {r['ingredient_name']}({r['ingredient_eng_name']}) "
                f"| 구분: {r['regulate_type']} | 국가: {r['country_name']}\n{content}"
            )
    return "\n".join(lines)


def buildPrompt(systemPrompt, context, userQuery):
    """
    시스템 프롬프트 + Context + 사용자 질문을 결합한 최종 프롬프트 생성.
    반환: 프롬프트 문자열
    """
    prompt = f"""{systemPrompt}

{context}

[질문]
{userQuery}

[답변]"""
    return prompt


# ============================================================
# LLM 답변 생성
# ============================================================

_BYTE_TOKEN_RE = re.compile(r'(?:<0x[0-9A-Fa-f]{2}>)+')


def fixByteFallbackTokens(text):
    """
    Ollama/llama.cpp가 병합하지 못한 byte-fallback 토큰(예: <0xEB><0x89><0xBC>)을
    원래 UTF-8 문자로 복원한다. gemma4:e4b의 vocab에 없는 희귀 한글 음절이
    이런 형태로 새어나오는 것을 확인함(예: '그래뉼'의 '뉼').
    """
    def repl(m):
        hexBytes = re.findall(r'0x([0-9A-Fa-f]{2})', m.group(0))
        raw = bytes(int(h, 16) for h in hexBytes)
        return raw.decode("utf-8", errors="replace")
    return _BYTE_TOKEN_RE.sub(repl, text)


_SUGGESTION_SECTION_RE = re.compile(r'\[추천질문\]\s*(.*)', re.DOTALL)
_SUGGESTION_LINE_RE    = re.compile(r'^\s*\d+[.\)]\s*(.+)$')


def extractSuggestions(answer):
    """
    답변 끝의 '[추천질문]' 섹션에서 후속 질문을 최대 2개 분리해낸다.
    LLM 생성 1회 안에서 답변과 함께 뽑아내므로 추가 지연이 없다.
    반환: (섹션이 제거된 답변, 후속 질문 리스트)
    """
    m = _SUGGESTION_SECTION_RE.search(answer)
    if not m:
        return answer, []

    mainAnswer  = answer[:m.start()].rstrip()
    suggestions = []
    for line in m.group(1).strip().split("\n"):
        lm = _SUGGESTION_LINE_RE.match(line.strip())
        if lm:
            suggestions.append(lm.group(1).strip())
        if len(suggestions) == 2:
            break

    return mainAnswer, suggestions


def filterGroundedSuggestions(osClient, cfg, suggestions):
    """
    LLM이 지어낸 추천질문 중 실제 검색 결과가 없는 항목을 제거한다.
    추천질문은 Context를 참고해 생성되긴 하지만 검색 가능 여부가 검증되지 않아,
    그럴듯하지만 실제로는 law-articles/hazard-products 어디에도 없는 질문이
    섞여 나올 수 있었다(클릭 시 "관련 정보를 찾지 못했습니다"로 이어짐).
    법령/안전정보 각각 topK=1로만 조회하는 가벼운 확인이라 지연시간에 영향 없음.
    """
    grounded = []
    for suggestion in suggestions:
        lawHit    = searchHybrid(osClient, cfg, suggestion, topK=1)
        hazardHit = searchHazardHybrid(osClient, cfg, suggestion, topK=1)
        if lawHit or hazardHit:
            grounded.append(suggestion)
    return grounded


_SOURCE_LEAK_RE = re.compile(r'\n*\[출처\].*?(?=\[추천질문\]|\Z)', re.DOTALL)


def stripSourceMentions(text):
    """
    안전장치: 프롬프트에 "답변 본문에 출처를 언급하지 마세요" 지시가 있음에도
    LLM이 자체적으로 [출처] 섹션을 생성하는 경우를 대비해 답변에서 제거한다.
    [추천질문] 섹션(있다면)은 [출처] 뒤에 와도 보존한다.
    """
    return _SOURCE_LEAK_RE.sub('', text)


_SUMMARY_SECTION_RE = re.compile(r'\[요약\]\s*(.+?)(?=\[포인트\]|$)', re.DOTALL)
_POINTS_SECTION_RE   = re.compile(r'\[포인트\]\s*(.+)', re.DOTALL)


def parseStructuredAnswer(rawText):
    """
    [요약]/[포인트] 형식(카드 렌더링용)으로 생성된 답변을 파싱해 구조화한다.
    [추천질문] 섹션은 extractSuggestions()가 먼저 떼어내므로 rawText에는 없다고 가정.
    LLM이 형식을 안 지켰을 경우 summary/points가 비고, raw에 원문이 그대로 남는다
    (프론트 fallback 렌더링용).
    반환: {"summary": str, "points": [{"title": str, "body": str}, ...], "raw": str}
    """
    summaryMatch = _SUMMARY_SECTION_RE.search(rawText)
    summary = summaryMatch.group(1).strip() if summaryMatch else ""

    pointsSection = _POINTS_SECTION_RE.search(rawText)
    points = []
    if pointsSection:
        for line in pointsSection.group(1).strip().split("\n"):
            line = re.sub(r'^\s*\d+\.\s*', '', line.strip())
            if "|" in line:
                title, body = line.split("|", 1)
                points.append({"title": title.strip(), "body": body.strip()})

    # 파싱 실패 시(형식을 안 지켰을 경우) 원문 그대로 fallback
    if not summary and not points:
        return {"summary": "", "points": [], "raw": rawText.strip()}

    return {"summary": summary, "points": points, "raw": ""}


_COUNT_REQUEST_RE = re.compile(r'(\d+)\s*(개|가지|건)')


def wantsSpecificCount(query):
    """
    사용자 질문에 "N개/가지/건" 패턴이 있으면 그 숫자를 반환한다 (없으면 None).
    이 값이 있으면 [요약]/[포인트] 카드 형식 대신 [목록] 형식 프롬프트를 사용한다 —
    "최대 4개까지"인 카드 형식이 "10개 알려줘" 같은 구체적 개수 요청과 충돌해
    LLM이 개수를 무시하고 뭉뚱그려 답하는 문제를 피하기 위함.
    """
    match = _COUNT_REQUEST_RE.search(query)
    return int(match.group(1)) if match else None


_RECALL_KEYWORDS     = ["회수", "판매중지", "판매 중지", "리콜"]
_INGREDIENT_KEYWORDS = ["성분", "원료", "배합한도", "사용제한", "함유", "함량"]


def detectHazardApiType(query):
    """
    질문 텍스트에서 recall(회수·판매중지)/ingredient(사용제한 원료) 의도를 키워드로 감지한다.
    apiType 필터 없이 hazard-products 전체를 시맨틱 검색하면 ingredient 문서(4,079건)가
    recall 문서(31건)보다 131배 많아, "회수된 제품 알려줘" 같은 recall 의도 질문에서도
    recall 문서가 topK 밖으로 밀려나 검색되지 않는 문제를 확인함(2026-07-06). 질문 의도가
    명확한 경우에만 apiType으로 좁혀 검색하고, 애매하거나 둘 다 섞여 있으면 None(전체)을
    유지해 기존 동작을 보존한다.
    반환: "recall" | "ingredient" | None
    """
    hasRecall     = any(kw in query for kw in _RECALL_KEYWORDS)
    hasIngredient = any(kw in query for kw in _INGREDIENT_KEYWORDS)
    if hasRecall and not hasIngredient:
        return "recall"
    if hasIngredient and not hasRecall:
        return "ingredient"
    return None


def getDynamicHazardTopK(query):
    """
    hazard-products 검색 시 사용할 topK를 질문 내용에 따라 동적으로 결정한다.
    평소 질문(개수 미지정)은 HAZARD_TOP_K(기본값)를 그대로 사용해 빠르게 응답하고,
    "N개 알려줘" 같은 질문일 때만 요청 개수만큼 topK를 올려(상한 MAX_HAZARD_TOP_K)
    느려지더라도 정확한 개수를 채울 후보를 확보한다.
    """
    requested = wantsSpecificCount(query)
    if requested is None:
        return HAZARD_TOP_K
    return min(requested, MAX_HAZARD_TOP_K)


_LIST_SECTION_RE = re.compile(r'\[목록\]\s*(.+)', re.DOTALL)


def parseListAnswer(rawText, requestedCount):
    """
    [목록] 형식(개수 지정 질문용)으로 생성된 답변을 파싱한다.
    [추천질문] 섹션은 extractSuggestions()가 먼저 떼어내므로 rawText에는 없다고 가정.
    LLM이 형식을 안 지켰을 경우(temperature>0이라 매번 100% 지키진 않음) list_items가
    비고, raw에 원문이 그대로 남는다 (프론트 fallback 렌더링용).
    반환: {"list_items": [...], "requested_count": int, "raw": str}
    """
    listSection = _LIST_SECTION_RE.search(rawText)
    items = []
    if listSection:
        for line in listSection.group(1).strip().split("\n"):
            line = re.sub(r'^\s*\d+\.\s*', '', line.strip())
            if "|" in line:
                name, desc = line.split("|", 1)
                items.append({"name": name.strip(), "desc": desc.strip()})

    # 파싱 실패 시(형식을 안 지켰을 경우) 원문 그대로 fallback
    if not items:
        return {"list_items": [], "requested_count": requestedCount, "raw": rawText.strip()}

    return {"list_items": items, "requested_count": requestedCount, "raw": ""}


def generateAnswer(cfg, prompt, stream=False):
    """
    Ollama Gemma4:e4b 모델로 답변 생성.
    stream=False : 전체 응답을 한 번에 반환
    stream=True  : 스트리밍 출력 (Spring API 연동용)
    반환: 답변 문자열
    """
    url     = cfg['ollamaHost'].rstrip("/") + GENERATE_API_PATH
    payload = {
        "model":  cfg['llmModel'],
        "prompt": prompt,
        "stream": stream,
        "options": {
            "temperature": 0.1,   # 법률 답변이므로 낮은 temperature
            "num_ctx":     8192,
        }
    }

    resp = requests.post(url, json=payload, timeout=300)
    resp.raise_for_status()

    if not stream:
        data = resp.json()
        text = fixByteFallbackTokens(data.get("response", ""))
        return stripSourceMentions(text)
    else:
        answer = ""
        for line in resp.iter_lines():
            if line:
                chunk = json.loads(line)
                answer += chunk.get("response", "")
                if chunk.get("done"):
                    break
        text = fixByteFallbackTokens(answer)
        return stripSourceMentions(text)


# ============================================================
# RAG 실행
# ============================================================

def runRag(osClient, cfg, userQuery, sector=None, topK=TOP_K):
    """
    RAG 파이프라인 전체 실행.
    1. 하이브리드 검색 → 2. Context 구성 → 3. LLM 답변 생성
    반환: {"answer": str, "sources": list, "results": list}
    """
    # STEP A: 하이브리드 검색
    results = searchHybrid(osClient, cfg, userQuery, sector=sector, topK=topK)
    if not results:
        return {
            "summary":         "",
            "points":          [],
            "raw_fallback":    "관련 법령을 찾지 못했습니다. 질문을 다시 입력해 주세요.",
            "list_items":      [],
            "requested_count": None,
            "sources":         [],
            "results":         [],
            "suggestions":     [],
        }

    # STEP B: Context 및 프롬프트 구성 (질문에 "N개/가지/건"이 있으면 목록 형식 프롬프트 사용)
    context = buildContext(results)
    requestedCount = wantsSpecificCount(userQuery)
    if requestedCount is not None:
        prompt = buildPrompt(SYSTEM_PROMPT_LIST, context, userQuery)
    else:
        prompt = buildPrompt(SYSTEM_PROMPT, context, userQuery)

    # STEP C: LLM 답변 생성 + 파싱
    answer = generateAnswer(cfg, prompt, stream=False)
    answer, suggestions = extractSuggestions(answer)

    # STEP D: 출처 목록 구성
    sources = []
    for i in range(0, len(results)):
        r = results[i]
        sources.append(
            f"{r['law_name']} 제{r['article_no']}조 {r['clause_no']}항"
        )

    if requestedCount is not None:
        listResult = parseListAnswer(answer.strip(), requestedCount)
        return {
            "summary":         "",
            "points":          [],
            "raw_fallback":    listResult["raw"],
            "list_items":      listResult["list_items"],
            "requested_count": listResult["requested_count"],
            "sources":         sources,
            "results":         results,
            "suggestions":     suggestions,
        }

    structured = parseStructuredAnswer(answer.strip())
    return {
        "summary":         structured["summary"],
        "points":          structured["points"],
        "raw_fallback":    structured["raw"],
        "list_items":      [],
        "requested_count": None,
        "sources":         sources,
        "results":         results,
        "suggestions":     suggestions,
    }


# ============================================================
# 통합 RAG 실행 (법령 + 안전정보, LLM 생성 1회)
# ============================================================

def runCombinedRag(osClient, cfg, userQuery, sector=None, topK=TOP_K, hazardTopK=None):
    """
    법령(law-articles) + 안전정보(hazard-products) 검색을 모두 수행하되,
    LLM 생성은 한 번만 호출하는 통합 RAG 파이프라인.
    1. 하이브리드 검색 2회(법령/안전정보, 둘 다 OpenSearch라 빠름) → 2. Context 병합 → 3. LLM 생성 1회
    hazardTopK : 미지정(None)이면 getDynamicHazardTopK()로 질문 내용에 따라 자동 결정
    반환: {"answer": str, "sources": list, "results": list}
    """
    if hazardTopK is None:
        hazardTopK = getDynamicHazardTopK(userQuery)
    print(f"[INFO] hazard topK 결정: {hazardTopK} (query='{userQuery[:30]}...')")

    # STEP A: 검색 (법령 + 안전정보, 둘 다 실행 — 병목 아님)
    hazardApiType = detectHazardApiType(userQuery)
    lawResults    = searchHybrid(osClient, cfg, userQuery, sector=sector, topK=topK)
    hazardResults = searchHazardHybrid(osClient, cfg, userQuery, apiType=hazardApiType, topK=hazardTopK)

    if not lawResults and not hazardResults:
        return {
            "summary":          "",
            "points":           [],
            "raw_fallback":     "관련 정보를 찾지 못했습니다. 질문을 다시 입력해 주세요.",
            "list_items":       [],
            "requested_count":  None,
            "truncated_notice": "",
            "sources":          [],
            "results":          [],
            "suggestions":      [],
        }

    # STEP B: Context 병합 (있는 섹션만 포함)
    contextParts = []
    if lawResults:
        contextParts.append(buildContext(lawResults))
    if hazardResults:
        contextParts.append(buildHazardContext(hazardResults))
    context = "\n\n".join(contextParts)

    # STEP C: LLM 답변 생성 (한 번만 호출) + 파싱 (질문에 "N개/가지/건"이 있으면 목록 형식 프롬프트 사용)
    requestedCount  = wantsSpecificCount(userQuery)
    truncatedNotice = ""
    if requestedCount is not None:
        prompt = buildPrompt(SYSTEM_PROMPT_LIST_COMBINED, context, userQuery)
        if requestedCount > MAX_HAZARD_TOP_K:
            truncatedNotice = f"요청하신 {requestedCount}개 중 자료 확보 가능한 {MAX_HAZARD_TOP_K}개까지만 확인해드립니다."
    else:
        prompt = buildPrompt(SYSTEM_PROMPT_COMBINED, context, userQuery)

    answer = generateAnswer(cfg, prompt, stream=False)
    answer, suggestions = extractSuggestions(answer)
    suggestions = filterGroundedSuggestions(osClient, cfg, suggestions)

    # STEP D: 출처 목록 병합
    sources = []
    for i in range(0, len(lawResults)):
        r = lawResults[i]
        sources.append(f"{r['law_name']} 제{r['article_no']}조 {r['clause_no']}항")
    for i in range(0, len(hazardResults)):
        r = hazardResults[i]
        if r["api_type"] == "recall":
            sources.append(f"{r['product_name']} (회수·판매중지)")
        else:
            sources.append(f"{r['ingredient_name']} (사용제한 원료·{r['country_name']})")

    if requestedCount is not None:
        listResult = parseListAnswer(answer.strip(), requestedCount)
        return {
            "summary":          "",
            "points":           [],
            "raw_fallback":     listResult["raw"],
            "list_items":       listResult["list_items"],
            "requested_count":  listResult["requested_count"],
            "truncated_notice": truncatedNotice,
            "sources":          sources,
            "results":          lawResults,
            "suggestions":      suggestions,
        }

    structured = parseStructuredAnswer(answer.strip())
    return {
        "summary":          structured["summary"],
        "points":           structured["points"],
        "raw_fallback":     structured["raw"],
        "list_items":       [],
        "requested_count":  None,
        "truncated_notice": "",
        "sources":          sources,
        "results":          lawResults,   # FastAPI 응답 스키마(SearchResult)가 법령 필드 전용이라 법령 결과만 포함
        "suggestions":      suggestions,
    }


# ============================================================
# 결과 출력 (CLI용)
# ============================================================

def printRagResult(ragResult, userQuery):
    """RAG 결과를 콘솔에 포매팅하여 출력."""
    print(f"\n{'='*60}")
    print(f"  Q: {userQuery}")
    print(f"{'='*60}")
    if ragResult.get("list_items"):
        print(f"\n[목록] (요청 개수: {ragResult['requested_count']})")
        for i, item in enumerate(ragResult["list_items"]):
            print(f"  {i+1}. {item['name']} | {item['desc']}")
    elif ragResult["raw_fallback"]:
        print(f"\n[파싱 실패 — 원문 그대로]\n{ragResult['raw_fallback']}")
    else:
        print(f"\n[요약] {ragResult['summary']}")
        for i, p in enumerate(ragResult["points"]):
            print(f"  {i+1}. {p['title']} | {p['body']}")
    print(f"\n{'─'*40}")
    print(f"검색된 조문 {len(ragResult['results'])}건:")
    for i in range(0, len(ragResult['sources'])):
        print(f"  [{i+1}] {ragResult['sources'][i]}")


# ============================================================
# 메인 (CLI 테스트)
# ============================================================

def main():
    """
    RAG 파이프라인 CLI 테스트 함수.
    """
    parser = argparse.ArgumentParser(description="에스테틱 법률 RAG 파이프라인 테스트")
    parser.add_argument("query",             help="질문 텍스트")
    parser.add_argument("--sector", default=None,
                        help="sector 필터 (위생관리/화장품규제/의료행위)")
    parser.add_argument("--topk",   default=5, type=int, help="검색 결과 수 (기본: 5)")
    args = parser.parse_args()

    # STEP 1: 설정 로드 및 클라이언트 초기화
    cfg      = loadConfig()
    osClient = getOsClient(cfg)

    # STEP 2: 검색 파이프라인 확인
    ensurePipeline(osClient)

    # STEP 3: RAG 실행
    print(f"[검색 중] '{args.query}'")
    try:
        ragResult = runRag(osClient, cfg, args.query, sector=args.sector, topK=args.topk)
    except Exception as e:
        print({"success": False, "message": f"RAG 실패: {e}"})
        sys.exit(1)

    # STEP 4: 결과 출력
    printRagResult(ragResult, args.query)


if __name__ == "__main__":
    main()
