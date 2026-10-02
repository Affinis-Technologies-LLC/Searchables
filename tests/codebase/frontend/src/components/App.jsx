import UserCard from './UserCard';
const { format } = require('../util');

export class App extends React.Component {
  render() { this.helper(); return <UserCard id={format(1)} />; }
  helper() {}
}
