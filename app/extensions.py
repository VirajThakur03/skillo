import os
import threading
import time
from collections import defaultdict, deque
from functools import wraps

from flask import jsonify, request
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()
migrate = Migrate()
bcrypt = Bcrypt()
jwt = JWTManager()


from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    strategy="fixed-window"
)
socketio = SocketIO(
    async_mode=os.getenv("SOCKETIO_ASYNC_MODE", "threading"),
)
