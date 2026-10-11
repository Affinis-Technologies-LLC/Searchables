package com.shop.service;

public class Audit {
    public void record(String what, long id) {
        System.out.println(what + " " + id);
    }
}
