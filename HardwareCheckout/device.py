from base64 import b64decode
from datetime import datetime, timedelta
from functools import wraps

from flask import abort, Blueprint, request, Response, session
from flask_socketio import disconnect, join_room, Namespace, send
from sqlalchemy.orm.exc import NoResultFound
from werkzeug.security import check_password_hash

from . import db, socketio, timer
from .models import DeviceQueue, UserQueue

device = Blueprint('device', __name__)


def auth_device():
    if 'Authorization' not in request.headers or not request.headers['Authorization'].startswith('Basic '):
        return None
    name, password = b64decode(request.headers['Authorization'][6:]).decode('latin1').split(':', 1)
    try:
        return DeviceQueue.query.filter_by(name=name).one()
    except NoResultFound:
        return None


def device_login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        device = auth_device()
        if not device:
            abort(Response(status=401, headers={'WWW-Authenticate': 'Basic realm="CarHackingVillage"'}))
        return func(*args, **kwargs, device=device)
    return wrapper


class DeviceNamespace(Namespace):
    def on_connect(self):
        device = auth_device()
        if not device:
            disconnect()
            return False
        session['device_id'] = device.id
        join_room('device:%i' % device.id)

    def on_message(self, json):
        device_id = session['device_id']
        device = DeviceQueue.query.filter_by(id=device_id)
        if not device:
            disconnect()
            return False
        else:
            device_put.__wrapped__.__wrapped__(**json, device=device)


def json_api(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        json = request.get_json()
        if not json:
            abort(415)
        json.update(kwargs)
        return func(*args, **json)
    return wrapper


@device.route('/state', methods=['PUT'])
@device_login_required
@json_api
def device_put(device, state, ssh=None, web=None, web_ro=None):
    device.sshAddr = ssh
    device.webUrl = web
    device.roUrl = web_ro
    db.session.add(device)
    if state not in ('ready', 'in-use', 'provisioning'):
        return {'result': 'error', 'error': 'invalid state'}, 400
    if state == device.state:
        db.session.commit()
        socketio.send({'state': device.state}, json=True, namespace='/device', room='device:%i' % device.id)
        return {'result': 'success'}
    {
        'ready': device_ready,
        'in-use': device_in_use,
        'provisioning': device_provisioning
    }[state](device)
    socketio.send({'state': device.state}, json=True, namespace='/device', room='device:%i' % device.id)
    return {'result': 'success'}


def device_ready(device):
    device_id = device.id
    if device.state == 'in-queue':
        if datetime.now() < device.expiration:
            delta = device.expiration - datetime.now()
            timer.rm_timer(device.timer)
            device.timer = timer.add_timer(lambda: device_ready(DeviceQueue.query.filter_by(id=device_id).one()), delta.total_seconds() + 1)
            db.session.add(device)
            db.session.commit()
            return
        else:
            socketio.send({'message': 'device_lost', 'device': device.type}, json=True, room='user:%i' % device.owner, namespace='/queue')
    next_user = UserQueue.query.filter_by(type=device.type).order_by(UserQueue.id).first()
    if not next_user:
        device.state = 'ready'
        device.expiration = None
        device.owner = None
    else:
        device.state = 'in-queue'
        device.expiration = datetime.now() + timedelta(minutes=5)
        device.owner = next_user.id
        device.timer = timer.add_timer(lambda: device_ready(DeviceQueue.query.filter_by(id=device_id).one()), 301)
        socketio.send({'message': 'device_available', 'device': device.type}, json=True, room='user:%i' % device.owner, namespace='/queue')
        db.session.delete(next_user)
    db.session.add(device)
    db.session.commit()


def device_in_use(device):
    device.state = 'in-use'
    device.expiration = datetime.now() + timedelta(minutes=30)
    timer.rm_timer(device.timer)
    db.session.add(device)
    db.session.commit()


def device_provisioning(device):
    device.state = 'provisioning'
    device.expiration = None
    db.session.add(device)
    db.session.commit()


def restart_all_timers():
    for device in DeviceQueue.query:
        if device.state in ('ready', 'in-queue'):
            device_ready(device)
