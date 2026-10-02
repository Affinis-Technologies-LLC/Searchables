package com.acme.web;

import com.acme.model.User;
import com.acme.service.Repository;
import com.acme.service.UserService;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/users")
public class UserController {
    private final Repository repository;
    private final UserService service = new UserService();

    public UserController(Repository repository) {
        this.repository = repository;
    }

    @GetMapping("/{id}")
    public User get(@PathVariable long id) {
        return repository.find(id).orElse(new User(id));
    }

    @PostMapping
    public void create(@RequestBody User user) {
        service.save(user, true);
        unknownThing().save(user);
    }
}
