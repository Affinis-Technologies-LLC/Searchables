package com.shop.model;

public class Customer {
    private long id;
    private String name;

    public Customer(long id) { this.id = id; }
    public long getId() { return id; }
    public String getName() { return name; }
}
