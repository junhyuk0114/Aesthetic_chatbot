package com.mazel.esthetic.dto;

import lombok.Getter;
import lombok.Setter;

import java.time.LocalDateTime;

@Getter
@Setter
public class CollectionLogDto {

    private int id;
    private String source;
    private LocalDateTime startedAt;
    private LocalDateTime finishedAt;
    private Integer totalFetched;
    private Integer totalIndexed;
    private String status;
    private String errorMessage;
    private String note;
}
