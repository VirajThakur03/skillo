# app/routes/chat.py
from flask import Blueprint, request, jsonify, current_app
from flask_socketio import emit, join_room, leave_room
from ..extensions import socketio, db
from ..models import Message, User, Booking
from flask_jwt_extended import decode_token
from datetime import datetime
from flask_jwt_extended.exceptions import NoAuthorizationError, InvalidHeaderError
from flask_jwt_extended import exceptions as jwt_exceptions

chat_bp = Blueprint("chat", __name__)


# REST endpoint to fetch message history for a room
@chat_bp.route("/room/<room>", methods=["GET"])
def get_room_history(room):
    messages = (
        Message.query.filter_by(room=room)
        .order_by(Message.created_at.asc())
        .limit(500)
        .all()
    )
    out = []
    for m in messages:
        out.append(
            {
                "id": m.id,
                "room": m.room,
                "sender_id": m.sender_id,
                "sender_name": m.sender.name if m.sender else None,
                "content": m.content,
                "created_at": m.created_at.isoformat(),
            }
        )
    return jsonify(out)


# used by register_routes() to attach socket handlers
def socket_handlers(app):
    @socketio.on("connect")
    def handle_connect(auth):
        """
        Socket.IO connection point. The client should send { auth: { token: "JWT..." } }
        during io() initialization. We will decode and attach user identity to session.
        """
        sid = request.sid
        token = None
        try:
            # socket.io passes auth payload as first arg in many clients
            if isinstance(auth, dict):
                token = auth.get("token")
        except Exception:
            token = None

        if token:
            try:
                decoded = decode_token(token)
                user_id = decoded.get("sub")  # identity stored as sub by flask-jwt-extended
                # Optionally verify user exists
                user = User.query.get(user_id)
                if user:
                    print(f"Socket connect: user {user_id} ({user.email}) sid={sid}")
                    emit("connected", {"msg": "connected", "user_id": user_id})
                    return True
                else:
                    print("Socket token user not found")
            except Exception as e:
                print("Socket auth decode error:", str(e))

        # if we reach here, reject connection
        print("Unauthorized socket connection rejected; disconnecting", sid)
        return False  # returning False disconnects the client in flask-socketio

    @socketio.on("join")
    def handle_join(data):
        room = data.get("room")
        if not room:
            return
        join_room(room)
        emit("joined", {"room": room}, to=room)

    @socketio.on("leave")
    def handle_leave(data):
        room = data.get("room")
        if not room:
            return
        leave_room(room)
        emit("left", {"room": room}, to=room)

    @socketio.on("message")
    def handle_message(data):
        """
        Expect data: { room: 'skill_1', message: 'hello', token: '...' } or token
        was passed during connect. We'll try to find sender id via token (prefer
        token in connect/auth).
        """
        room = data.get("room")
        msg_text = data.get("message") or data.get("content")
        sender_id = None

        # try to get token from payload (safer to send token at connect and keep it)
        token = None
        try:
            if isinstance(data, dict):
                token = data.get("token")
        except Exception:
            token = None

        if token:
            try:
                decoded = decode_token(token)
                sender_id = decoded.get("sub")
            except Exception:
                sender_id = None

        # Save message into DB
        if room and msg_text:
            m = Message(
                room=room,
                sender_id=sender_id,
                content=msg_text,
                created_at=datetime.utcnow(),
            )
            db.session.add(m)
            db.session.commit()
            emit(
                "message",
                {
                    "id": m.id,
                    "room": m.room,
                    "sender_id": m.sender_id,
                    "sender_name": m.sender.name if m.sender else None,
                    "content": m.content,
                    "created_at": m.created_at.isoformat(),
                },
                to=room,
            )

    @socketio.on("worker_location")
    def handle_worker_location(data):
        """
        data: { booking_id, latitude, longitude, token }
        """
        booking_id = data.get("booking_id")
        lat = data.get("latitude")
        lon = data.get("longitude")
        token = data.get("token")

        if not booking_id or lat is None or lon is None or not token:
            return

        try:
            decoded = decode_token(token)
            user_id = decoded.get("sub")
        except Exception:
            return

        booking = Booking.query.get(booking_id)
        if not booking or booking.provider_id != user_id:
            # only assigned provider may update location
            return

        try:
            booking.worker_latitude = float(lat)
            booking.worker_longitude = float(lon)
        except Exception:
            return

        booking.worker_last_seen_at = datetime.utcnow()
        db.session.commit()

        room = f"booking_{booking.id}"
        emit(
            "worker_location_update",
            {
                "booking_id": booking.id,
                "latitude": booking.worker_latitude,
                "longitude": booking.worker_longitude,
                "last_seen_at": booking.worker_last_seen_at.isoformat(),
            },
            to=room,
        )
