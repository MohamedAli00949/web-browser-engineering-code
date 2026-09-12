import socket
import urllib
import random
import html

s = socket.socket(
    family=socket.AF_INET,
    type=socket.SOCK_STREAM,
    proto=socket.IPPROTO_TCP)

s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

s.bind(('', 8000))
s.listen()

SESSIONS = {}

def handle_connection(conx):
    req = conx.makefile("b")
    reqline = req.readline().decode('utf8')
    method, url, version = reqline.split(" ", 2)
    assert method in ["GET", "POST"]

    headers = {}
    while True:
        line = req.readline().decode('utf8')
        if line == '\r\n': break
        header, value = line.split(":", 1)
        headers[header.casefold()] = value.strip()

    if 'cookie' in headers:
        token = headers['cookie'][len("token="):]
    else:
        token = str(random.random())[2:]

    session = SESSIONS.setdefault(token, {})

    if 'content-length' in headers:
        length = int(headers['content-length'])
        body = req.read(length).decode('utf8')
    else:
        body = None

    status, body = do_request(session, method, url, headers, body)

    response = "HTTP/1.0 {}\r\n".format(status)
    response += "Content-Length: {}\r\n".format(len(body.encode("utf8")))

    if 'cookie' not in headers:
        response += "Set-Cookie: token={}; SameSite=Lax\r\n".format(token)

    csp = "default-src http://localhost:8000"
    response += "Content-Security-Policy: {}\r\n".format(csp)

    response += "\r\n" + body
    conx.send(response.encode('utf8'))
    conx.close()

ENTRIES = [
    ("No names. We are nameless!", "cerealkiller"),
    ("HACK THE PLANET!!!", "crashoverride"),
]

LOGINS = {
    "crashoverride": "0cool",
    "cerealkiller": "emmanuel"
}

def do_request(session, method, url, headers, body):
    out = "<!doctype html>"
    # for entry in ENTRIES:
    #     out += "<p>" + entry + "</p>"

    # out += "<form action=add method=post>"
    # out +=   "<p><input name=guest></p>"
    # out +=   "<p><button>Sign the book!</button></p>"
    # out += "</form>"

    if method == "GET" and url == "/":
        return "200 OK", show_comments(session, out)
    elif method == "GET" and url == "/login":
        return "200 OK", login_form(session)
    elif method == "POST" and url == "/login":
        params = form_decode(body)
        return do_login(session, params)
    elif method == "POST" and url == "/add":
        params = form_decode(body)
        add_entry(session, params, out)
        return "200 OK", show_comments(session)
    elif method == "GET" and url == "/comment.js":
        with open("comment.js") as f:
            return "200 OK", f.read()
    elif method == "GET" and url.endswith(".js"):
        try:
            filename = url.lstrip("/")
            with open(filename, "r") as f:
                return "200 OK", f.read()
        except FileNotFoundError:
            return "404 Not Found", not_found(url, method)
    elif method == "GET" and url == "/count":
        return "200 OK", show_count(session, out)
    else:
        return "404 Not Found", not_found(url, method, out)

def show_count(session, out):
    out = "<!doctype html>"
    out += "<div>"
    out += " Let's count up to 99!"
    out += "</div>"
    out += "<div>Output</div>"
    out += "<script src=/eventloop.js></script>"

    return out

def show_comments(session, out):
    # ...
    if "user" in session:
        nonce = str(random.random())[2:]
        session["nonce"] = nonce

        out += "<h1>Hello, " + session["user"] + "</h1>"
        out += "<form action=add method=post>"
        out += "<input name=nonce type=hidden value=" + nonce + ">"
        out += "<p><input name=guest></p>"
        out += "<p><button>Sign the book!</button></p>"
        out += "</form>"
    else:
        out += "<a href=/login>Sign in to write in the guest book</a>"

    for entry, who in ENTRIES:
        out += "<p>" + html.escape(entry) + "\n"
        out += "<i>by " + html.escape(who) + "</i></p>"

    out += "<strong></strong>"
    out += "<script src=/comment.js></script>"
    out += "<script src=https://example.com/evil.js></script>"

    # ...
    return out

def form_decode(body):
    params = {}
    for field in body.split("&"):
        name, value = field.split("=", 1)
        name = urllib.parse.unquote_plus(name)
        value = urllib.parse.unquote_plus(value)
        params[name] = value
    return params

def add_entry(session, params, out):
    if "user" not in session: return
    if "nonce" not in session or "nonce" not in params: return
    if session["nonce"] != params["nonce"]: return
    if 'guest' in params and len(params['guest']) <= 100:
        ENTRIES.append((params['guest'], session['user']))
    return show_comments(session, out)

def not_found(url, method, out):
    out = "<!doctype html>"
    out += "<h1>{} {} not found!</h1>".format(method, url)
    return out

def login_form(session):
    out = "<!doctype html>"
    out += "<form action=/login method=post>"
    out +=   "<p>Username: <input name=username></p>"
    out +=   "<p>Password: <input name=password type=password></p>"
    out +=   "<p><button>Log in</button></p>"
    out += "</form>"
    return out

def do_login(session, params):
    username = params.get("username")
    password = params.get("password")
    if username in LOGINS and LOGINS[username] == password:
        session["user"] = username
        return "200 OK", show_comments(session)
    else:
        out = "<!doctype html>"
        out += "<h1>Invalid password for {}</h1>".format(username)
        return "401 Unauthorized", out

while True:
    conx, addr = s.accept()
    handle_connection(conx)
