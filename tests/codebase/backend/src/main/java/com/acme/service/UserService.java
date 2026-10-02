package com.acme.service;

import com.acme.model.User;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

public class UserService implements Repository {
    private final List<User> users = new ArrayList<>();

    @Override
    public Optional<User> find(long id) {
        return users.stream().filter(u -> u.getId() == id).findFirst();
    }

    @Override
    public void save(User user) {
        audit("save");
        users.add(user);
    }

    public void save(User user, boolean notify) {
        save(user);
    }

    private void audit(String what) {
        System.out.println(what);
    }
}
