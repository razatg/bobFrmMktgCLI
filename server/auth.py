from __future__ import annotations
import hashlib, hmac, secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import HTTPException, Request

def hash_password(password: str) -> str: return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
def check_password(password: str, encoded: str) -> bool:
    try: return bcrypt.checkpw(password.encode(), encoded.encode())
    except (ValueError, TypeError): return False
def hash_code(code: str) -> str: return hashlib.sha256(code.encode()).hexdigest()
def same_code(code: str, digest: str) -> bool: return hmac.compare_digest(hash_code(code), digest)

async def current_user(request: Request):
    store = request.app.state.store; row = store.session_user(request.cookies.get('bob_session'))
    if not row: raise HTTPException(401, 'authentication required')
    if row['status'] != 'approved': raise HTTPException(403, 'account is not approved')
    return row

async def csrf(request: Request):
    user = await current_user(request)
    if request.method not in {'GET','HEAD','OPTIONS'}:
        sid = request.cookies.get('bob_session'); token = request.headers.get('X-CSRF-Token')
        session = request.app.state.store.one('SELECT csrf_token FROM sessions WHERE id=?',(sid,))
        if not session or not token or not hmac.compare_digest(token, session['csrf_token']): raise HTTPException(403, 'csrf check failed')
    return user
