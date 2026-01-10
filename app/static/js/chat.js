// app/static/js/chat.js
// (not necessary if inline script used in template; included for extension)
const socket = io();

function joinRoom(room){
  socket.emit('join', {room});
}

function sendMessage(room, message){
  socket.emit('message', {room, message});
}

socket.on('message', (data) => {
  console.log('message', data);
});
