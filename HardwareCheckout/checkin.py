from flask import Blueprint, render_template, abort, request, jsonify, redirect, url_for
from flask_login import current_user, login_required
from flask_user import roles_required
import datetime 

from . import db, socketio
from .models import User, UserQueue, DeviceQueue, DeviceType

checkin = Blueprint('checkin', __name__)

@checkin.route("/checkin", methods=['POST'])
@roles_required("Device")
def return_device():
    """
    This path will allow a client to return their device to the queue
    """
    # import pdb
    # pdb.set_trace()
    msg = {"status":"error"}
    content = request.get_json(force=True)
    
    try:
        sshAddr = content['ssh']
        web_url = content['web']
        ro_url = content['web_ro']
    except KeyError:
        abort(404)

    queueEntry = db.session.query(DeviceQueue).filter_by(device=current_user.id).first()
    if queueEntry:
        queueEntry.sshAddr = sshAddr
        queueEntry.webUrl = web_url
        queueEntry.roUrl = ro_url
        queueEntry.inUse = False
        queueEntry.inReadyState = False
    else:
        # create a device entry for this device
        queueEntry = DeviceQueue(
            sshAddr = sshAddr,
            webUrl = web_url,
            roUrl = ro_url,
            device = current_user.id,
            inUse = False,
            inReadyState = False,
            # owner = user.id if queuedUser and user else None,
            # expiration = datetime.datetime.now() + datetime.timedelta(minutes=5),
        )
        db.session.add(queueEntry)

    nextUser = db.session.query(UserQueue).filter_by(type=1).first()
    if nextUser:
        socketio.send({"message": "device_available", "device": queueEntry.id}, json=True, room=str(nextUser.userId))

    db.session.commit()
    msg['status'] = "success"

    return jsonify(msg)

@checkin.route("/terminals", methods=["GET"])
def listTerminals():

    results = db.session.query(DeviceQueue.roUrl).all()
    return jsonify(results)

@checkin.route("/terminals/rw", methods=["GET"])
@roles_required("Admin")
def listRWTerminals():
    results = db.session.query(DeviceQueue.webUrl,DeviceQueue.sshAddr).all()
    return jsonify(results)
 
@checkin.route("/register/<device>", methods=["GET"])
@roles_required("Human")
def requestDevice(device):
    devType = db.session.query(DeviceType).filter_by(name=device).first()
    if not devType:
        abort(404)

    if db.session.query(DeviceQueue).filter_by(owner=current_user.id,inUse=True).first():
        return render_template("error.html", error="You already have a device in use.")
    
    if db.session.query(UserQueue).filter_by(userId=current_user.id, type=devType.id).first():
        return render_template("error.html", error="You already in the queue for {}.".format(devType.name))

    db.session.add(UserQueue(userId=current_user.id, type=devType.id))
    db.session.commit()
    return redirect(url_for("main.index"))
