package com.mazel.esthetic.dto;

import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
public class ChatRequest {

    private String query;
    private String sector;
    private int topk = 5;
}
