package com.acme.service;

import com.acme.model.User;
import java.util.Optional;

public interface Repository {
    Optional<User> find(long id);
    void save(User user);
}
