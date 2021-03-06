from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import current_user, LoginManager
from flask_user import UserManager
from flask_socketio import SocketIO
import os
import json
from datetime import datetime, timedelta
from .config import db_path

# init SQLAlchemy so we can use it later in our models
db = SQLAlchemy()


def create_app():
    """

    :return:
    """
    app = Flask(__name__)

    app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', open(os.path.join(os.path.dirname(os.path.realpath(__file__)), "../db.key"),'r').read())
    app.config['SQLALCHEMY_DATABASE_URI'] = db_path
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)

    global socketio
    socketio = SocketIO(app)

    from .timer import Timer
    global timer
    timer = Timer()

    from .models import User, Role
    UserManager.USER_ENABLE_EMAIL = False
    user_manager = UserManager(app, db, User)
    user_manager.login_manager.login_view = 'auth.login'

    # @user_manager.login_manager.user_loader
    # def load_user(user_id):
    #     """

    #     :param user_id:
    #     :return:
    #     """
    #     return User.query.get(int(user_id))

    # blueprint for auth routes in our app
    from .auth import auth as auth_blueprint
    app.register_blueprint(auth_blueprint)

    # blueprint for non-auth parts of app
    from .main import main as main_blueprint
    app.register_blueprint(main_blueprint)
    from .checkin import checkin as checkin_blueprint
    app.register_blueprint(checkin_blueprint)
    from .device import device as device_blueprint, restart_all_timers, DeviceNamespace
    app.register_blueprint(device_blueprint, url_prefix='/device')
    socketio.on_namespace(DeviceNamespace('/device'))
    timer.add_timer('/device/timer', datetime.now() + timedelta(seconds=2))
    from .queue import queue as queue_blueprint, QueueNamespace
    app.register_blueprint(queue_blueprint, url_prefix='/queue')
    socketio.on_namespace(QueueNamespace('/queue'))
    from .user import user as user_blueprint
    app.register_blueprint(user_blueprint, url_prefix='/user')

    return app
