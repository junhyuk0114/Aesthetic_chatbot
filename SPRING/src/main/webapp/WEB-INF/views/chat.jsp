<%@ page language="java" contentType="text/html; charset=UTF-8" pageEncoding="UTF-8"%>
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>마젤원향 — 에스테틱 법률·안전 자문</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }

        body {
            font-family: 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif;
            background: #f5f5f7;
            display: flex;
            flex-direction: column;
            height: 100vh;
        }

        header {
            background: #1c2438;
            color: #f5f5f7;
            padding: 14px 20px;
            display: flex;
            align-items: center;
            gap: 12px;
        }

        header h1 { font-size: 1.1rem; font-weight: 600; }
        header span { font-size: 0.75rem; color: #b89a5c; }

        #chat-window {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 14px;
        }

        .msg {
            max-width: 75%;
            padding: 12px 16px;
            border-radius: 12px;
            line-height: 1.6;
            font-size: 0.9rem;
            word-break: break-word;
            white-space: pre-wrap;
        }

        .msg.user {
            background: #1c2438;
            color: #f5f5f7;
            align-self: flex-end;
            border-top-right-radius: 4px;
        }

        .msg.bot {
            background: #fff;
            color: #1c2438;
            align-self: flex-start;
            border-top-left-radius: 4px;
            border-left: 3px solid #b89a5c;
            box-shadow: 0 1px 4px rgba(0,0,0,0.08);
        }

        .msg.loading { color: #999; font-style: italic; }

        /* ── 요약 박스 ── */
        .summary-box {
            background: #f0f1f4;
            border-radius: 8px;
            padding: 10px 12px;
            font-size: 13px;
            font-weight: 500;
            color: #1c2438;
            margin-bottom: 12px;
        }

        /* ── 포인트 카드 ── */
        .points-wrap {
            display: flex;
            flex-direction: column;
        }

        .point-row {
            display: flex;
            gap: 10px;
            margin-bottom: 12px;
        }

        .point-row:last-child { margin-bottom: 0; }

        .point-badge {
            flex-shrink: 0;
            width: 22px;
            height: 22px;
            border-radius: 50%;
            background: #1c2438;
            color: #b89a5c;
            font-size: 12px;
            font-weight: 600;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .point-body { flex: 1; min-width: 0; }

        .point-title {
            font-size: 13px;
            font-weight: 500;
            color: #1c2438;
            margin-bottom: 2px;
        }

        .point-text {
            font-size: 12.5px;
            line-height: 1.65;
            color: #3a4258;
        }

        /* ── 개수 지정 목록(list_items) 카드 ── */
        .list-header {
            font-size: 12px;
            color: #8a8f9c;
            margin-bottom: 10px;
        }

        .list-item-row {
            display: flex;
            gap: 10px;
            margin-bottom: 10px;
        }

        .list-item-row:last-child { margin-bottom: 0; }

        .list-item-name {
            font-size: 13px;
            font-weight: 500;
            color: #1c2438;
            margin-bottom: 2px;
        }

        .list-item-desc {
            font-size: 12.5px;
            line-height: 1.6;
            color: #3a4258;
        }

        /* ── 출처: 한 줄 축약, 클릭하면 펼침/접힘 토글 ── */
        .sources-row {
            display: flex;
            align-items: flex-start;
            gap: 4px;
            min-width: 0;   /* flex item 기본값(min-width:auto)이 ellipsis를 무력화하는 것 방지 */
            font-size: 0.78rem;
            color: #8a8f9c;
            margin-top: 8px;
            padding-top: 8px;
            border-top: 1px solid #eee;
        }

        .sources-text {
            flex: 1;
            min-width: 0;   /* 위와 동일한 이유 — 부모뿐 아니라 이 요소 자체에도 필요 */
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            cursor: pointer;
        }

        .sources-text.expanded {
            white-space: normal;
            text-overflow: clip;
            overflow: visible;
        }

        .sources-arrow {
            flex-shrink: 0;
            display: flex;
            margin-top: 2px;
            transition: transform 0.2s;
        }

        .sources-text.expanded ~ .sources-arrow { transform: rotate(180deg); }

        /* ── 피드백(좋아요/싫어요) ── */
        .feedback-bar {
            display: flex;
            gap: 4px;
            margin-top: 8px;
        }

        .feedback-btn {
            border: none;
            background: transparent;
            color: #b0b4bf;
            padding: 4px;
            border-radius: 6px;
            cursor: pointer;
            display: flex;
            align-items: center;
            transition: color 0.15s, background 0.15s;
        }

        .feedback-btn:hover { background: #f2f2f2; color: #1c2438; }
        .feedback-btn.active-up   { color: #1a9e4a; }
        .feedback-btn.active-down { color: #d0393e; }
        .feedback-btn.thumbs-down svg { transform: rotate(180deg); }

        /* ── 빠른 질문(추천 질문) 칩 ── */
        .suggestions {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-top: 10px;
        }

        .suggestion-chip {
            padding: 7px 14px;
            border: 1px solid #d8dbe2;
            border-radius: 6px;
            background: #fff;
            color: #3a4258;
            cursor: pointer;
            font-size: 0.78rem;
            transition: all 0.2s;
        }

        .suggestion-chip:hover { background: #1c2438; color: #f5f5f7; border-color: #1c2438; }

        /* ── 입력 영역 ── */
        #input-area {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 10px 14px;
            background: #fff;
            border-top: 1px solid #e0e0e0;
        }

        #query-input {
            flex: 1;
            padding: 12px 18px;
            border: 1px solid #d8dbe2;
            border-radius: 8px;
            font-size: 0.9rem;
            outline: none;
            resize: none;
            min-height: 44px;
            max-height: 120px;
        }

        #query-input::placeholder { color: #a0a4b0; }

        #mic-btn,
        #send-btn {
            flex-shrink: 0;
            width: 44px;
            height: 44px;
            border-radius: 6px;
            border: none;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
        }

        #mic-btn {
            background: #f0f1f4;
            color: #3a4258;
        }

        #mic-btn:hover { background: #e5e7ec; }

        #send-btn {
            background: #1c2438;
            color: #b89a5c;
        }

        #send-btn:disabled { background: #999; cursor: not-allowed; }
    </style>
</head>
<body>

<header>
    <div>
        <h1>마젤원향 법률·안전 자문 AI</h1>
        <span>공중위생관리법 · 화장품법 · 의료법 기반 RAG</span>
    </div>
</header>

<div id="chat-window">
    <div class="msg bot">안녕하세요! 에스테틱 법률·안전 자문 AI입니다.<br>
마케팅 문구 적법성, 시술 행위 기준, 화장품 광고 규정 등을 질문해 보세요.</div>
</div>

<div id="input-area">
    <textarea id="query-input" placeholder="예: 인스타에 여드름 치료 전문샵이라고 써도 되나요?" rows="1"></textarea>
    <button id="mic-btn" type="button" title="음성 입력(준비 중)">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="9" y="2" width="6" height="11" rx="3"/>
            <path d="M5 10v1a7 7 0 0 0 14 0v-1M12 18v3M9 21h6"/>
        </svg>
    </button>
    <button id="send-btn" type="button" title="전송">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 19V5M5 12l7-7 7 7"/>
        </svg>
    </button>
</div>

<script>
    // 답변 말풍선의 좋아요/싫어요 버튼용 인라인 SVG (thumbs-up / thumbs-down)
    // thumbs-down은 thumbs-up과 같은 path를 180도 회전시켜 재사용 (.feedback-btn.thumbs-down svg { transform: rotate(180deg) })
    var THUMBS_SVG =
        '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M7 10v11H4a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1h3zm0 0l4.34-7.87a1 1 0 0 1 1.75.9L12 8h6a2 2 0 0 1 2 2.3l-1.2 8A2 2 0 0 1 16.83 20H10a2 2 0 0 1-2-2V10z"/>' +
        '</svg>';

    // 출처 펼침/접힘 토글 화살표 아이콘 (chevron)
    var SOURCES_ARROW_SVG =
        '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">' +
        '<path d="M6 9l6 6 6-6"/>' +
        '</svg>';

    // HTML 특수문자 이스케이프 (innerHTML로 렌더링하기 전 XSS 방지용)
    function escapeHtml(str) {
        return str
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    // point body의 **핵심 문구**를 하이라이트 span으로 변환 (이스케이프 후 치환)
    function highlightKeyPhrases(text) {
        const escaped = escapeHtml(text);
        return escaped.replace(
            /\*\*(.+?)\*\*/g,
            '<span style="background:#f5e9d0;color:#7a5f2e;padding:1px 4px;border-radius:3px;">$1</span>'
        );
    }

    const chatWindow  = document.getElementById("chat-window");
    const queryInput  = document.getElementById("query-input");
    const sendBtn     = document.getElementById("send-btn");
    const micBtn      = document.getElementById("mic-btn");

    queryInput.addEventListener("keydown", e => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    queryInput.addEventListener("input", () => {
        queryInput.style.height = "auto";
        queryInput.style.height = Math.min(queryInput.scrollHeight, 120) + "px";
    });

    sendBtn.addEventListener("click", sendMessage);

    // Placeholder: STT(음성 입력) 미구현. 클릭 시 안내 alert만 표시.
    micBtn.addEventListener("click", () => {
        alert("음성 입력 준비 중입니다.");
    });

    // [요약]/[포인트] 카드 렌더링 (container = appendMsg가 만든 .msg 엘리먼트)
    function renderStructuredAnswer(container, data) {
        // 요약 박스
        const summaryBox = document.createElement("div");
        summaryBox.className = "summary-box";
        summaryBox.textContent = data.summary;
        container.appendChild(summaryBox);

        // 포인트 카드 (번호 배지 + 소제목 + 본문, 본문의 **강조**는 하이라이트 span으로 변환)
        if (data.points && data.points.length > 0) {
            const pointsWrap = document.createElement("div");
            pointsWrap.className = "points-wrap";

            data.points.forEach((p, idx) => {
                const pointRow = document.createElement("div");
                pointRow.className = "point-row";

                const badge = document.createElement("div");
                badge.className = "point-badge";
                badge.textContent = String(idx + 1);

                const pointBody = document.createElement("div");
                pointBody.className = "point-body";

                const pointTitle = document.createElement("div");
                pointTitle.className = "point-title";
                pointTitle.textContent = p.title;

                const pointText = document.createElement("div");
                pointText.className = "point-text";
                pointText.innerHTML = highlightKeyPhrases(p.body);

                pointBody.appendChild(pointTitle);
                pointBody.appendChild(pointText);

                pointRow.appendChild(badge);
                pointRow.appendChild(pointBody);
                pointsWrap.appendChild(pointRow);
            });

            container.appendChild(pointsWrap);
        }
    }

    // 개수 지정 질문(list_items) 카드 렌더링
    function renderListItems(container, data) {
        const items          = data.list_items;
        const requestedCount = data.requested_count;

        const header = document.createElement("div");
        header.className = "list-header";
        header.textContent = (items.length === requestedCount)
            ? (items.length + "개를 안내드립니다")
            : ("요청하신 " + requestedCount + "개 중 " + items.length + "개를 찾았습니다");
        container.appendChild(header);

        function buildItemRow(item, idx) {
            const row = document.createElement("div");
            row.className = "list-item-row";

            const badge = document.createElement("div");
            badge.className = "point-badge";   // 포인트 카드와 동일한 배지 스타일 재사용
            badge.textContent = String(idx + 1);

            const body = document.createElement("div");
            body.className = "point-body";     // 포인트 카드와 동일한 본문 레이아웃 재사용

            const nameEl = document.createElement("div");
            nameEl.className = "list-item-name";
            nameEl.textContent = item.name;

            const descEl = document.createElement("div");
            descEl.className = "list-item-desc";
            descEl.textContent = item.desc;

            body.appendChild(nameEl);
            body.appendChild(descEl);
            row.appendChild(badge);
            row.appendChild(body);
            return row;
        }

        const listWrap = document.createElement("div");
        listWrap.className = "points-wrap";
        items.forEach((item, idx) => listWrap.appendChild(buildItemRow(item, idx)));
        container.appendChild(listWrap);
    }

    function appendMsg(text, role, sources, suggestions, summary, points, listItems, requestedCount) {
        const div = document.createElement("div");
        div.className = "msg " + role;

        if (role === "bot" && listItems && listItems.length > 0) {
            renderListItems(div, { list_items: listItems, requested_count: requestedCount });
        } else if (role === "bot" && summary) {
            renderStructuredAnswer(div, { summary: summary, points: points });
        } else {
            // list_items/summary가 없는 경우(사용자 메시지, 로딩, 에러, 파싱 실패 raw_fallback) 기존 방식대로 처리
            div.textContent = text;
        }

        if (sources && sources.length > 0) {
            const srcRow = document.createElement("div");
            srcRow.className = "sources-row";

            const srcText = document.createElement("span");
            srcText.className = "sources-text";
            const fullSources = "[출처] " + sources.join(" | ");
            srcText.textContent = fullSources;

            const arrowSpan = document.createElement("span");
            arrowSpan.className = "sources-arrow";
            arrowSpan.innerHTML = SOURCES_ARROW_SVG;

            srcRow.appendChild(srcText);
            srcRow.appendChild(arrowSpan);

            // srcText 클릭 시 펼침/접힘 토글 (.expanded 클래스 추가·제거)
            srcText.addEventListener("click", () => {
                srcText.classList.toggle("expanded");
            });

            div.appendChild(srcRow);
        }

        // suggestions가 없거나 빈 배열이면 렌더링하지 않는 방어 코드
        if (suggestions && suggestions.length > 0) {
            const sugDiv = document.createElement("div");
            sugDiv.className = "suggestions";
            suggestions.forEach(s => {
                const chip = document.createElement("button");
                chip.type = "button";
                chip.className = "suggestion-chip";
                chip.textContent = s;
                chip.addEventListener("click", () => {
                    queryInput.value = s;
                    sendMessage();
                });
                sugDiv.appendChild(chip);
            });
            div.appendChild(sugDiv);
        }

        // 봇의 실제 답변에만 좋아요/싫어요 버튼 추가 (로딩 말풍선 제외)
        if (role === "bot") {
            const fbDiv = document.createElement("div");
            fbDiv.className = "feedback-bar";

            const upBtn = document.createElement("button");
            upBtn.type = "button";
            upBtn.className = "feedback-btn thumbs-up";
            upBtn.title = "도움이 됐어요";
            upBtn.innerHTML = THUMBS_SVG;

            const downBtn = document.createElement("button");
            downBtn.type = "button";
            downBtn.className = "feedback-btn thumbs-down";
            downBtn.title = "도움이 안 됐어요";
            downBtn.innerHTML = THUMBS_SVG;

            upBtn.addEventListener("click", () => {
                upBtn.classList.add("active-up");
                downBtn.classList.remove("active-down");
                console.log("[FEEDBACK] up:", text);
                // TODO: POST /api/feedback { query, answer: text, rating: "up" }
            });
            downBtn.addEventListener("click", () => {
                downBtn.classList.add("active-down");
                upBtn.classList.remove("active-up");
                console.log("[FEEDBACK] down:", text);
                // TODO: POST /api/feedback { query, answer: text, rating: "down" }
            });

            fbDiv.appendChild(upBtn);
            fbDiv.appendChild(downBtn);
            div.appendChild(fbDiv);
        }

        chatWindow.appendChild(div);
        chatWindow.scrollTop = chatWindow.scrollHeight;
        return div;
    }

    function sendMessage() {
        const query = queryInput.value.trim();
        if (!query) return;

        appendMsg(query, "user");
        queryInput.value = "";
        queryInput.style.height = "auto";
        sendBtn.disabled = true;

        const loadingDiv = appendMsg("답변 생성 중...", "bot loading");

        fetch("/api/chat", {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({
                query:  query,
                sector: null,
                topk:   5
            })
        })
        .then(r => r.json())
        .then(data => {
            loadingDiv.remove();
            if (data.success) {
                appendMsg(data.raw_fallback, "bot", data.sources, data.suggestions, data.summary, data.points,
                          data.list_items, data.requested_count);
            } else {
                appendMsg("오류: " + (data.message || "답변 생성에 실패했습니다."), "bot");
            }
        })
        .catch(err => {
            loadingDiv.remove();
            appendMsg("서버 연결 오류: " + err.message, "bot");
        })
        .finally(() => {
            sendBtn.disabled = false;
            queryInput.focus();
        });
    }
</script>

</body>
</html>
