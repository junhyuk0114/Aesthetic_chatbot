package com.mazel.esthetic.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.mazel.esthetic.dto.ChatRequest;
import com.mazel.esthetic.dto.ChatResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

@Service
public class RagService {

    @Value("${rag.server.url}")
    private String ragServerUrl;

    private final ObjectMapper objectMapper = new ObjectMapper();

    /**
     * FastAPI RAG 서버(/rag/query)로 질문을 전달하고 답변을 반환.
     * /rag/query가 법령·안전정보 검색을 내부적으로 병합해 답변 하나를 만들어 준다.
     * @param req 사용자 질문 + 필터 정보
     * @return ChatResponse (answer, sources, results)
     */
    public ChatResponse query(ChatRequest req) {
        try {
            Map<String, Object> payload = new HashMap<>();
            payload.put("query",  req.getQuery());
            payload.put("sector", req.getSector());
            payload.put("topk",   req.getTopk());

            String requestBody = objectMapper.writeValueAsString(payload);

            URL url = new URL(ragServerUrl + "/rag/query");
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setRequestProperty("Content-Type", "application/json; charset=UTF-8");
            conn.setConnectTimeout(10_000);
            conn.setReadTimeout(300_000);   // gemma4:e4b 응답 대기
            conn.setDoOutput(true);

            try (OutputStream os = conn.getOutputStream()) {
                os.write(requestBody.getBytes(StandardCharsets.UTF_8));
            }

            int statusCode = conn.getResponseCode();
            if (statusCode != 200) {
                return ChatResponse.builder()
                        .success(false)
                        .message("RAG 서버 오류: HTTP " + statusCode)
                        .build();
            }

            String responseBody = new String(conn.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
            ChatResponse resp = objectMapper.readValue(responseBody, ChatResponse.class);
            resp.setSuccess(true);
            return resp;

        } catch (Exception e) {
            return ChatResponse.builder()
                    .success(false)
                    .message("RAG 서버 연결 실패: " + e.getMessage())
                    .build();
        }
    }
}
