package com.mazel.esthetic.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.util.List;

@Getter
@Setter
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ChatResponse {

    private boolean success;
    private String message;
    private String summary;
    private List<PointDto> points;
    private String raw_fallback;
    private List<ListItemDto> list_items;
    private Integer requested_count;
    private String truncated_notice;
    private List<String> sources;
    private List<SearchResultDto> results;
    private List<String> suggestions;

    @Getter
    @Setter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class PointDto {
        private String title;
        private String body;
    }

    @Getter
    @Setter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class ListItemDto {
        private String name;
        private String desc;
    }

    @Getter
    @Setter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class SearchResultDto {
        private int rank;
        private double score;
        private String law_name;
        private String article_no;
        private String clause_no;
        private String sector;
        private String title;
        private String content;
        private String effective_date;
    }
}
