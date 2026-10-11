import { NgModule } from '@angular/core';
import { AppComponent } from './app.component';
import { UserListComponent } from './users/user-list.component';

@NgModule({ declarations: [AppComponent, UserListComponent], bootstrap: [AppComponent] })
export class AppModule {}
