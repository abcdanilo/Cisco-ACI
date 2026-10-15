"""Opaque browser sessions; APIC tokens and report caches stay in server memory."""
import secrets
import threading
import time
from urllib.parse import urlsplit

import requests
from flask import g, request, redirect, jsonify, render_template, make_response
from werkzeug.exceptions import Unauthorized


class LoginSession:
    def __init__(self):
        self.sid = secrets.token_urlsafe(32)
        self.csrf = secrets.token_urlsafe(32)
        self.username = ''
        self.token = ''
        self.seen = time.monotonic()
        self.refresh_at = 0
        self.valid = True
        self.lock = threading.RLock()
        self.cache = {}


class Auth:
    cookie = 'aci_session'

    def __init__(self, app, apic_url, verify, timeout, idle_seconds, secure):
        self.app, self.url, self.verify, self.timeout = app, apic_url.rstrip('/'), verify, timeout
        self.idle_seconds, self.secure = idle_seconds, secure
        self.sessions = {}
        self.lock = threading.RLock()
        app.config['MAX_CONTENT_LENGTH'] = 16 * 1024
        app.before_request(self.guard)
        app.after_request(self.finish)
        app.add_url_rule('/login', 'login', self.login, methods=['GET', 'POST'])
        app.add_url_rule('/logout', 'logout', self.logout, methods=['POST'])
        threading.Thread(target=self.sweep, daemon=True, name='aci-session-expiry').start()

    def sweep(self):
        while True:
            time.sleep(30)
            self.expire()

    def expire(self):
        now = time.monotonic()
        with self.lock:
            expired = [s for s in self.sessions.values() if now-s.seen >= (self.idle_seconds if s.token else 300)]
        for state in expired:
            with state.lock:
                if time.monotonic()-state.seen >= (self.idle_seconds if state.token else 300):
                    self.remove(state)

    def create(self):
        self.expire()
        state = LoginSession()
        with self.lock:
            if len(self.sessions) >= 2000:
                return None
            self.sessions[state.sid] = state
        return state

    def remove(self, state):
        with state.lock:
            state.valid = False
            state.token = ''
            state.cache.clear()
        with self.lock:
            self.sessions.pop(state.sid, None)

    def current(self):
        with self.lock:
            state = self.sessions.get(request.cookies.get(self.cookie, ''))
        if state:
            with state.lock:
                if not state.valid or time.monotonic()-state.seen >= (self.idle_seconds if state.token else 300):
                    self.remove(state)
                    return None
        return state

    @staticmethod
    def destination(value):
        value = value or '/'
        try:
            parts = urlsplit(value)
        except ValueError:
            return '/'
        if parts.scheme or parts.netloc or not parts.path.startswith('/') or value.startswith('//') or '\\' in value or any(ord(c)<32 for c in value):
            return '/'
        if parts.path in ('/login', '/logout') or parts.path.startswith(('/api/', '/export_csv/')):
            return '/'
        return parts.path + ('?'+parts.query if parts.query else '')

    def cookie_response(self, response, state):
        response.set_cookie(self.cookie, state.sid, httponly=True, secure=self.secure, samesite='Lax', path='/')
        return response

    def denied(self):
        if request.path.startswith(('/api/', '/export_csv/')):
            response = make_response(jsonify(error='Sessão expirada. Entre novamente.', login_url='/login'), 401)
        else:
            from urllib.parse import urlencode
            response = redirect('/login?'+urlencode({'next':self.destination(request.full_path.rstrip('?'))}))
        if self.current() is None:
            response.delete_cookie(self.cookie, path='/', secure=self.secure, httponly=True, samesite='Lax')
        response.headers['Cache-Control'] = 'no-store'
        return response

    def csrf_valid(self, state):
        supplied = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token', '')
        return bool(state and supplied and secrets.compare_digest(state.csrf, supplied))

    def guard(self):
        if request.path == '/favicon.ico':
            return '', 204
        if request.endpoint == 'static' or request.path == '/login':
            return None
        state = self.current()
        if not state or not state.token:
            return self.denied()
        g.auth = state
        with state.lock:
            if not state.valid:
                return self.denied()
            if request.method not in ('GET', 'HEAD', 'OPTIONS') and not self.csrf_valid(state):
                return jsonify(error='Validação da sessão inválida. Atualize a página.'), 403
            state.seen = time.monotonic()
            if request.path != '/logout' and state.seen >= state.refresh_at:
                try:
                    response = requests.get(self.url+'/api/aaaRefresh.json', headers={'Cookie':'APIC-cookie='+state.token},
                                            verify=self.verify, timeout=self.timeout, allow_redirects=False)
                    self.accept_token(state, response)
                except Exception:
                    self.remove(state)
                    return self.denied()

    def accept_token(self, state, response):
        if response.status_code != 200:
            raise ValueError('Authentication failed')
        data = response.json()['imdata'][0]['aaaLogin']['attributes']
        token = data['token']
        if not isinstance(token, str) or not token or '\r' in token or '\n' in token:
            raise ValueError('Invalid token')
        seconds = max(1, min(int(data.get('refreshTimeoutSeconds', 300)), 86400))
        state.token = token
        state.refresh_at = time.monotonic()+seconds*0.75

    def login(self):
        state = self.current()
        if state and state.token:
            return redirect(self.destination(request.args.get('next', '/')))
        if not state:
            if request.method == 'POST':
                return redirect('/login')
            state = self.create()
        if state is None:
            return 'Muitas sessões abertas. Tente novamente em alguns minutos.', 503
        error, status = '', 200
        destination = self.destination(request.values.get('next', '/'))
        if request.method == 'POST':
            if not self.csrf_valid(state):
                error, status = 'Formulário expirado. Tente novamente.', 403
            else:
                username, password = request.form.get('username', '').strip(), request.form.get('password', '')
                if not username or not password or len(username)>256 or len(password)>4096:
                    error, status = 'Informe usuário e senha válidos.', 400
                else:
                    authenticated = LoginSession()
                    try:
                        response = requests.post(self.url+'/api/aaaLogin.json',
                            json={'aaaUser':{'attributes':{'name':username,'pwd':password}}},
                            verify=self.verify, timeout=self.timeout, allow_redirects=False)
                        self.accept_token(authenticated, response)
                    except requests.RequestException:
                        error, status = 'Não foi possível conectar à APIC. Verifique conectividade e certificado.', 502
                    except (ValueError, KeyError, IndexError, TypeError):
                        error, status = 'A APIC não aceitou o login. Confira usuário, senha e domínio de autenticação.', 401
                    else:
                        authenticated.username = username
                        self.remove(state)
                        with self.lock:
                            self.sessions[authenticated.sid] = authenticated
                        return self.cookie_response(redirect(destination, code=303), authenticated)
                    finally:
                        password = None
                        # Never persist the POST body, PreparedRequest, response or password.
        response = make_response(render_template('login.html', csrf_token=state.csrf, destination=destination, error=error), status)
        return self.cookie_response(response, state)

    def logout(self):
        state = g.auth
        with state.lock:
            token, username = state.token, state.username
            self.remove(state)
        try:
            requests.post(self.url+'/api/aaaLogout.json', headers={'Cookie':'APIC-cookie='+token},
                          json={'aaaUser':{'attributes':{'name':username}}}, verify=self.verify,
                          timeout=self.timeout, allow_redirects=False)
        except requests.RequestException:
            pass
        return self.denied()

    def finish(self, response):
        if request.endpoint == 'static':
            return response
        state = getattr(g, 'auth', None)
        if state and not state.valid and request.path != '/logout':
            response = self.denied()
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Pragma'] = 'no-cache'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        if state and state.valid and response.mimetype == 'text/html' and response.status_code == 200:
            bar = render_template('session_bar.html', username=state.username, csrf_token=state.csrf)
            html = response.get_data(as_text=True).replace('<head>', '<head><script src="/static/auth-session.js"></script>', 1)
            response.set_data(html.replace('</body>', bar+'</body>'))
        return response

    def require(self):
        state = getattr(g, 'auth', None)
        if not state or not state.valid or not state.token:
            raise Unauthorized('Sessão expirada. Entre novamente.')
        return state
