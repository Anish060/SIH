"""
===============================================================================
OceanEmbed — users, roles and signed tokens (standard library only)
===============================================================================
Roles:  end_user < decision_maker, scientist < admin
  end_user        public dashboard (no login needed)
  decision_maker  + decision brief
  scientist       + science tools and data explorer
  admin           everything, including user management, jobs and system health

Passwords: scrypt (n=2^14, r=8, p=1, 16-byte salt). Tokens: HMAC-SHA256 signed
JSON {sub, role, exp}; secret from OCEANEMBED_SECRET or state/secret.key.
Create the first admin:  python auth.py add admin --role admin
===============================================================================
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.environ.get("OCEANEMBED_STATE_DIR", os.path.join(HERE, "state"))
ROLES = ("end_user", "decision_maker", "scientist", "admin")
ACCESS = {  # capability -> roles allowed
    "brief": {"decision_maker", "scientist", "admin"},
    "science": {"scientist", "admin"},
    "explorer": {"scientist", "admin"},
    "admin": {"admin"},
}
TOKEN_TTL_S = 12 * 3600


def _db():
    os.makedirs(STATE_DIR, exist_ok=True)
    con = sqlite3.connect(os.path.join(STATE_DIR, "oceanembed.db"))
    con.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, role TEXT NOT NULL, salt BLOB, hash BLOB, created REAL)")
    return con


def _secret():
    s = os.environ.get("OCEANEMBED_SECRET")
    if s:
        return s.encode()
    os.makedirs(STATE_DIR, exist_ok=True)
    p = os.path.join(STATE_DIR, "secret.key")
    if not os.path.exists(p):
        with open(p, "wb") as f:
            f.write(secrets.token_bytes(32))
        os.chmod(p, 0o600)
    return open(p, "rb").read()


def _hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)


def add_user(username, password, role):
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    salt = secrets.token_bytes(16)
    with _db() as con:
        con.execute("INSERT OR REPLACE INTO users VALUES (?,?,?,?,?)", (username, role, salt, _hash(password, salt), time.time()))


def delete_user(username):
    with _db() as con:
        con.execute("DELETE FROM users WHERE username=?", (username,))


def list_users():
    with _db() as con:
        return [{"username": u, "role": r, "created": c} for u, r, c in con.execute("SELECT username, role, created FROM users ORDER BY username")]


def verify(username, password):
    with _db() as con:
        row = con.execute("SELECT role, salt, hash FROM users WHERE username=?", (username,)).fetchone()
    if not row:
        _hash(password, b"0" * 16)        # same cost whether or not the user exists
        return None
    role, salt, h = row
    return role if hmac.compare_digest(_hash(password, salt), h) else None


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(username, role):
    body = _b64(json.dumps({"sub": username, "role": role, "exp": int(time.time()) + TOKEN_TTL_S}).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_token(token):
    try:
        body, sig = token.split(".")
        if not hmac.compare_digest(_b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest()), sig):
            return None
        claims = json.loads(_unb64(body))
        if claims["exp"] < time.time():
            return None
        with _db() as con:        # role changes / deletions take effect immediately
            row = con.execute("SELECT role FROM users WHERE username=?", (claims["sub"],)).fetchone()
        if not row:
            return None
        claims["role"] = row[0]
        return claims
    except Exception:
        return None


if __name__ == "__main__":
    import getpass
    if len(sys.argv) >= 3 and sys.argv[1] == "add":
        role = sys.argv[sys.argv.index("--role") + 1] if "--role" in sys.argv else "scientist"
        pw = getpass.getpass(f"Password for {sys.argv[2]}: ")
        add_user(sys.argv[2], pw, role)
        print(f"[✔] {sys.argv[2]} ({role})")
    elif len(sys.argv) >= 2 and sys.argv[1] == "list":
        for u in list_users():
            print(u["username"], u["role"])
    elif len(sys.argv) >= 3 and sys.argv[1] == "delete":
        delete_user(sys.argv[2])
    else:
        print("usage: python auth.py add <user> --role <end_user|decision_maker|scientist|admin> | list | delete <user>")
