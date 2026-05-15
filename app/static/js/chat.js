const TOKEN_KEY = "sklio_access_token";
const LEGACY_TOKEN_KEY = "skl_token";

let chatSocket = null;

export function chatToken() {
  return localStorage.getItem(TOKEN_KEY) || localStorage.getItem(LEGACY_TOKEN_KEY);
}

export function createChatSocket(token = null, { forceNew = false } = {}) {
  if (typeof io === "undefined") return null;
  if (!forceNew && chatSocket) return chatSocket;

  chatSocket = io({
    auth: { token: token || chatToken() || null },
    transports: ["websocket", "polling"],
  });
  return chatSocket;
}

export function getChatSocket() {
  return chatSocket;
}

export function joinRoom(room) {
  if (!chatSocket || !room) return;
  chatSocket.emit("join", { room, token: chatToken() });
}

export function leaveRoom(room) {
  if (!chatSocket || !room) return;
  chatSocket.emit("leave", { room, token: chatToken() });
}

export function sendMessage(room, message, clientId = null) {
  if (!chatSocket || !room || !message) return;
  chatSocket.emit("message", {
    room,
    message,
    client_id: clientId,
    token: chatToken()
  });
}

export function sendTyping(room, isTyping = true) {
  if (!chatSocket || !room) return;
  chatSocket.emit(isTyping ? "typing" : "typing_stop", { room, token: chatToken() });
}

export function sendHeartbeat() {
  if (!chatSocket) return;
  chatSocket.emit("heartbeat", { token: chatToken() });
}

export function onChatMessage(handler) {
  if (!chatSocket || typeof handler !== "function") return;
  chatSocket.on("message", handler);
}

export function onReadReceipt(handler) {
  if (!chatSocket || typeof handler !== "function") return;
  chatSocket.on("messages_read", handler);
}

export function onRoomError(handler) {
  if (!chatSocket || typeof handler !== "function") return;
  chatSocket.on("room_error", handler);
}
