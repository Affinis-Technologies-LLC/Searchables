const express = require('express');
const app = express();
app.get('/health', (req, res) => res.send('ok'));
app.delete('/api/users/:id/avatar', removeAvatar);
function removeAvatar(req, res) {}
