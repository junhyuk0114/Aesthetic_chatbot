package com.mazel.esthetic.controller;

import com.mazel.esthetic.dto.ChatRequest;
import com.mazel.esthetic.dto.ChatResponse;
import com.mazel.esthetic.mapper.CollectionLogMapper;
import com.mazel.esthetic.service.RagService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
@RequestMapping("/api")
public class ChatController {

    @Autowired
    private RagService ragService;

    @Autowired
    private CollectionLogMapper collectionLogMapper;

    /** 사용자 질문을 RAG로 처리하고 답변 반환 */
    @PostMapping("/chat")
    public ResponseEntity<ChatResponse> chat(@RequestBody ChatRequest req) {
        if (req.getQuery() == null || req.getQuery().isBlank()) {
            return ResponseEntity.badRequest()
                    .body(ChatResponse.builder()
                            .success(false)
                            .message("query가 비어 있습니다.")
                            .build());
        }
        ChatResponse resp = ragService.query(req);
        return ResponseEntity.ok(resp);
    }

    /** Spring 서버 헬스체크 */
    @GetMapping("/health")
    public ResponseEntity<Map<String, String>> health() {
        return ResponseEntity.ok(Map.of(
                "status",  "ok",
                "service", "에스테틱 법률 챗봇 (마젤원향)"
        ));
    }

    /** 최근 수집 로그 20건 조회 */
    @GetMapping("/logs")
    public ResponseEntity<?> logs() {
        try {
            return ResponseEntity.ok(collectionLogMapper.selectRecentLogs(20));
        } catch (Exception e) {
            return ResponseEntity.internalServerError()
                    .body(Map.of("success", false, "message", e.getMessage()));
        }
    }
}
