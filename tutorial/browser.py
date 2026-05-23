import socket
import ssl
import os
import gzip
import time
import tkinter

DEFAULT_FILE = "test/index.html"
WIDTH, HEIGHT = 800, 600
HSTEP, VSTEP = 13, 18
SCROLL_STEP = 100


def read_chunked(response):
    body = b""

    while True:
        chunk_size_line = response.readline().decode("utf8").strip()

        chunk_size_line = chunk_size_line.split(";", 1)[0]

        chunk_size = int(chunk_size_line, 16)

        if chunk_size == 0:
            response.readline()  # Consume trailing CRLF
            break

        chunk = response.read(chunk_size)
        body += chunk

        response.readline()

    return body


def cache_key(scheme, host, path):
    """Unique string key for this URL."""
    return f"{scheme}://{host}{path}"


def parse_cache_control(response_headers):
    """
    Returns (cacheable, max_age).
    cacheable = False if no-store or any unrecognized directive is present.
    max_age   = seconds to cache, or None if not specified.
    """
    if "cache-control" not in response_headers:
        return True, None  # no header → assume cacheable, no expiry

    directives = [d.strip() for d in response_headers["cache-control"].split(",")]
    max_age = None
    cacheable = True

    for directive in directives:
        if directive == "no-store":
            return False, None  # must not cache
        elif directive.startswith("max-age="):
            try:
                max_age = int(directive.split("=", 1)[1])
            except ValueError:
                cacheable = False
        elif directive == "no-cache":
            # no-cache means "revalidate", treat as not cacheable for simplicity
            cacheable = False
        # any other directive → don't cache
        elif directive not in ("public", "private", "must-revalidate"):
            cacheable = False

    return cacheable, max_age


def layout(text):
    display_list = []
    cursor_x, cursor_y = HSTEP, VSTEP
    for c in text:
        display_list.append((cursor_x, cursor_y, c))
        # if c == "\n":
        if cursor_x >= WIDTH - HSTEP:
            cursor_y += VSTEP
            cursor_x = HSTEP
        else:
            cursor_x += HSTEP

    return display_list


def lex(body):
    text = ""
    in_tag = False
    in_entity = False
    entity = ""

    for c in body:
        if in_entity:
            if c == ";":
                if entity == "lt":
                    # print("<", end="")
                    text += "<"
                elif entity == "gt":
                    # print(">", end="")
                    text += ">"
                else:
                    # print("&" + entity + ";", end="")
                    text += "&" + entity + ";"
                in_entity = False
                entity = ""
            else:
                entity += c
        elif c == "&" and not in_tag:
            in_entity = True
            entity = ""
        elif c == "<":
            in_tag = True
        elif c == ">":
            in_tag = False
        elif not in_tag:
            # print(c, end="")
            text += c

    return text

class URL:
    socket_cache = {}
    response_cache = {}

    def __init__(self, url):
        if url.startswith("view-source:"):
            self.scheme = "view-source"
            self.inner_url = URL(url[len("view-source:") :])

            self.host = None
            self.port = None
            self.path = None

        elif url.startswith("data:"):
            self.scheme = "data"

            url = url[len("data:") :]
            self.mimetype, self.data = url.split(",", 1)

            self.host = None
            self.port = None
            self.path = None

        else:
            self.scheme, url = url.split("://", 1)

            assert self.scheme in ["http", "https", "file"]

            if self.scheme == "file":
                if (
                    os.name == "nt"
                    and url.startswith("/")
                    and len(url) > 2
                    and url[2] == ":"
                ):
                    url = url[1:]

                self.path = url
                self.host = None
                self.port = None
            else:
                if "/" not in url:
                    url += "/"

                self.host, url = url.split("/", 1)
                self.path = "/" + url

                if ":" in self.host:
                    self.host, self.port = self.host.split(":", 1)
                    self.port = int(self.port)
                else:
                    self.port = 443 if self.scheme == "https" else 80

    def request(self, redirects=0):
        MAX_REDIRECTS = 10

        if self.scheme == "view-source":
            return self.inner_url.request()
        elif self.scheme == "data":
            if self.mimetype in ["text/html", "text/plain"]:
                return self.data
            else:
                return f"<p>Unsupported data type: {self.mimetype}</p>"
        elif self.scheme == "file":
            with open(self.path, "r", encoding="utf8") as f:
                return f.read()
        else:
            # ── cache lookup ───────────────────────────────────────────────
            key = cache_key(self.scheme, self.host, self.path)
            if key in URL.response_cache:
                entry = URL.response_cache[key]
                if entry["expires"] is None or time.time() < entry["expires"]:
                    return entry["content"]
                else:
                    del URL.response_cache[key]
            # ──────────────────────────────────────────────────────────────

            socket_key = (self.host, self.port)

            s = URL.socket_cache.get(socket_key)

            if s is None:
                s = socket.socket(
                    family=socket.AF_INET,
                    type=socket.SOCK_STREAM,
                    proto=socket.IPPROTO_TCP,
                )

                s.connect((self.host, self.port))

                if self.scheme == "https":
                    ctx = ssl.create_default_context()
                    s = ctx.wrap_socket(s, server_hostname=self.host)

            request_headers = {
                "Host": self.host,
                "Connection": "keep-alive",
                "User-Agent": "MoBrowserFromWebBrowserEngineeringBook/1.0",
                "Accept-Encoding": "identity",
            }

            request = f"GET {self.path} HTTP/1.1\r\n"

            for header, value in request_headers.items():
                request += f"{header}: {value}\r\n"

            request += "\r\n"

            s.send(request.encode("utf8"))

            response = s.makefile("rb")

            statusLine = response.readline().decode("utf8")

            version, status, explanation = statusLine.split(" ", 2)

            response_headers = {}

            while True:
                line = response.readline().decode("utf8")

                if line == "\r\n":
                    break
                header, value = line.split(":", 1)
                response_headers[header.casefold()] = value.strip()

            if status.startswith("3") and "location" in response_headers:
                if redirects >= MAX_REDIRECTS:
                    raise Exception("Too many redirects")

                redirect_url = response_headers["location"]
                s.close()
                URL.socket_cache.pop(socket_key, None)

                if redirect_url.startswith("/"):
                    redirect_url = f"{self.scheme}://{self.host}{redirect_url}"

                return URL(redirect_url).request(redirects=redirects + 1)

            if response_headers.get("transfer-encoding") == "chunked":
                content = read_chunked(response)

            elif "content-length" in response_headers:
                content_length = int(response_headers["content-length"])

                content = response.read(content_length)

            else:
                content = response.read()

            if response_headers.get("content-encoding") == "gzip":
                content = gzip.decompress(content)

            content = content.decode("utf8", errors="replace")

            if response_headers.get("connection", "").lower() == "close":
                s.close()
            else:
                URL.socket_cache[socket_key] = s

            if status == "200":
                cacheable, max_age = parse_cache_control(response_headers)
                if cacheable:
                    expires = (time.time() + max_age) if max_age is not None else None
                    URL.response_cache[key] = {"content": content, "expires": expires}

            return content


class Browser:
    def __init__(self):
        self.window = tkinter.Tk()
        self.canvas = tkinter.Canvas(self.window, width=WIDTH, height=HEIGHT)
        self.canvas.pack()
        self.display_list = []
        self.scroll = 0
        self.window.bind("<Up>", self.scrollup)
        self.window.bind("<Down>", self.scrolldown)

    def scrollup(self, e):
        self.scroll -= SCROLL_STEP
        self.draw()

    def scrolldown(self, e):
        self.scroll += SCROLL_STEP
        self.draw()

    def draw(self):
        self.canvas.delete("all")
        for x, y, c in self.display_list:
            if y > (self.scroll - VSTEP) + HEIGHT:
                continue
            if y + (VSTEP * 2) < self.scroll:
                continue
            self.canvas.create_text(x, y - (self.scroll), text=c, anchor="nw")

    def load(self, url):
        body = url.request()
        if url.scheme == "view-source":
            self.canvas.create_text(10, 10, text=body, anchor="nw")
        else:
            text = lex(body)
            self.display_list = layout(text)
            self.draw()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        url = URL(sys.argv[1])
        Browser().load(url)
    else:
        Browser().load(URL("file://" + DEFAULT_FILE))

    tkinter.mainloop()
