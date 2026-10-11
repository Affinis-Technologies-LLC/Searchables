import { Component } from '@angular/core';
import { User } from '@app/users/user.service';

@Component({
  selector: 'app-root',
  template: '<app-user-list [title]="heading" (selected)="onSelected($event)"></app-user-list>',
})
export class AppComponent {
  heading = 'Team';
  onSelected(user: User): void {
    console.log(user.name);
  }
}
