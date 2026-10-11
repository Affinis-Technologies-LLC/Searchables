package com.shop.model;

public class Order {
    private long id;
    private String status;

    public Order(long id) { this.id = id; }
    public long getId() { return id; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
}
