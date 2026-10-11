import { Component, EventEmitter, Input, OnInit, Output } from '@angular/core';
import { UserService, User } from '@app/users/user.service';

@Component({
  selector: 'app-user-list',
  templateUrl: './user-list.component.html',
})
export class UserListComponent implements OnInit {
  @Input() title = 'Users';
  @Output() selected = new EventEmitter<User>();
  users: User[] = [];

  constructor(private userService: UserService) {}

  ngOnInit(): void {
    this.userService.list().subscribe((users) => (this.users = users));
  }

  choose(user: User): void {
    this.selected.emit(user);
  }

  remove(user: User): void {
    this.userService.remove(user.id).subscribe(() => this.ngOnInit());
  }
}
