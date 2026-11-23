import hashlib
import hmac
import secrets
import time

from .db import now, uid
from .errors import AppError


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f'{salt}:{digest}'


def verify_password(password, stored):
    salt, expected = stored.split(':')
    actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return hmac.compare_digest(actual, expected)


def create_user(db, username, password, role):
    username = username.strip().lower()
    if not 3 <= len(username) <= 80 or not all(c.isalnum() or c in '._-@' for c in username):
        raise AppError(422, 'invalid_username', 'Use 3–80 letters, numbers, dots, hyphens, underscores, or @ for the username.')
    if not 10 <= len(password) <= 128:
        raise AppError(422, 'invalid_password', 'Passwords must contain 10–128 characters.')
    if role not in ('admin', 'reader'):
        raise AppError(422, 'invalid_role', 'Choose reader or admin.')
    if db.one('SELECT id FROM users WHERE username=?', (username,)):
        raise AppError(409, 'username_taken', 'That username already exists.')
    user_id = uid()
    db.execute('INSERT INTO users VALUES (?,?,?,?,?)', (user_id, username, hash_password(password), role, now()))
    return {'id': user_id, 'username': username, 'role': role}


def current_user(request):
    token = request.cookies.get('guidely_session', '')
    hashed = hashlib.sha256(token.encode()).hexdigest()
    user = request.app.state.service.db.one(
        'SELECT u.id,u.username,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>?',
        (hashed, time.time()))
    if not user:
        raise AppError(401, 'unauthenticated', 'Please sign in to continue.')
    return user


def require_admin(request):
    user = current_user(request)
    if user['role'] != 'admin':
        raise AppError(403, 'forbidden', 'An administrator account is required.')
    return user
