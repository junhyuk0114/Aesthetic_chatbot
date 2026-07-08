package com.mazel.esthetic.controller;

import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;

@Controller
public class PageController {

    @GetMapping({"/", "/chat"})
    public String chat() {
        return "chat";
    }
}
