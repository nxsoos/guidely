"""Local administrator setup and password recovery; no credentials in shell history."""
import argparse
from getpass import getpass

from .auth import create_user, hash_password
from .config import Settings
from .db import Database


def main():
    parser = argparse.ArgumentParser(description='Guidely account setup')
    parser.add_argument('command', choices=['create-admin', 'reset-password'])
    parser.add_argument('--username', required=True)
    args = parser.parse_args()
    password = getpass('Password (10–128 characters): ')
    if password != getpass('Confirm password: '):
        parser.error('Passwords do not match.')
    if not 10 <= len(password) <= 128:
        parser.error('Passwords must contain 10–128 characters.')
    db = Database(Settings().data_dir)
    if args.command == 'create-admin':
        create_user(db, args.username, password, 'admin')
    else:
        user = db.one('SELECT id FROM users WHERE username=?', (args.username.strip().lower(),))
        if not user:
            parser.error('Account not found.')
        db.execute('UPDATE users SET password=? WHERE id=?', (hash_password(password), user['id']))
        db.execute('DELETE FROM sessions WHERE user_id=?', (user['id'],))
    print('Account updated successfully.')


if __name__ == '__main__':
    main()
