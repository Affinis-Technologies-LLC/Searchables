package com.store.service;

public abstract class BaseService<T> {
    protected abstract T load(long id);
}
