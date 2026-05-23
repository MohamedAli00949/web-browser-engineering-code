import socket
import ssl
import os
import gzip
import time
import tkinter
from tkinter import font

DEFAULT_FILE = "test/index.html"
WIDTH, HEIGHT = 800, 600
HSTEP, VSTEP = 13, 18
SCROLL_STEP = 100

FONTS = {}


def get_font(size, weight, style):
    key = (size, weight, style)
    if key not in FONTS:
        f = font.Font(size=size, weight=weight, slant=style)
        label = tkinter.Label(font=f)
        FONTS[key] = (f, label)

    return FONTS[key][0]


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


def lex(body):
    out = []
    buffer = ""
    in_tag = False
    in_entity = False
    entity = ""

    for c in body:
        if in_entity:
            if c == ";":
                if entity == "lt":
                    # print("<", end="")
                    buffer += "<"
                elif entity == "gt":
                    # print(">", end="")
                    buffer += ">"
                else:
                    # print("&" + entity + ";", end="")
                    buffer += "&" + entity + ";"
                in_entity = False
                entity = ""
            else:
                entity += c
        elif c == "&" and not in_tag:
            in_entity = True
            entity = ""
        elif c == "<":
            in_tag = True
            if buffer:
                out.append(Text(buffer))
            buffer = ""
        elif c == ">":
            in_tag = False
            out.append(Tag(buffer))
            buffer = ""
        else:
            # print(c, end="")
            buffer += c

    if not in_tag and buffer:
        out.append(Text(buffer))

    return out


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


class Layout:
    def __init__(
        self,
        tokens,
    ):
        self.line = []
        self.display_list = []
        self.weight = "normal"
        self.style = "roman"
        self.cursor_x, self.cursor_y = HSTEP, VSTEP
        self.size = 12
        self.word_font = font.Font(
            family="Times", size=self.size, weight=self.weight, slant=self.style
        )

        for tok in tokens:
            self.token(tok)

        self.flush()

    def token(self, tok):
        if isinstance(tok, Text):
            for word in tok.text.split():
                self.word_font = font.Font(
                    family="Times",
                    size=self.size,
                    weight=self.weight,
                    slant=self.style,
                )
                self.word(word)

        elif tok.tag == "i":
            self.style = "italic"
        elif tok.tag == "/i":
            self.style = "roman"
        elif tok.tag == "b":
            self.weight = "bold"
        elif tok.tag == "/b":
            self.weight = "normal"
        elif tok.tag == "br":
            self.flush()
            self.cursor_x = HSTEP
            self.cursor_y += self.word_font.metrics("linespace") * 1.25
        elif tok.tag == "p" or tok.tag == "div":
            self.flush()
            self.cursor_y += VSTEP
        elif tok.tag == "pre":
            self.style = "roman"
            self.cursor_x = HSTEP
            self.cursor_y += self.word_font.metrics("linespace") * 1.25
        elif tok.tag == "h1":
            self.flush()
            self.size += 20
            self.cursor_x = HSTEP
            self.cursor_y += self.word_font.metrics("linespace") * 3.5
        elif tok.tag == "h2":
            self.flush()
            self.size += 10
            self.cursor_x = HSTEP
            self.cursor_y += self.word_font.metrics("linespace") * 2.5
        elif tok.tag == "h3":
            self.flush()
            self.size += 5
            self.cursor_x = HSTEP
            self.cursor_y += self.word_font.metrics("linespace") * 1.75
        elif tok.tag == "/h1":
            self.size -= 20
        elif tok.tag == "/h2":
            self.size -= 10
        elif tok.tag == "/h3":
            self.size -= 5
        elif tok.tag == "small":
            self.size -= 2
        elif tok.tag == "/small":
            self.size += 2
        elif tok.tag == "big":
            self.size += 4
        elif tok.tag == "/big":
            self.size -= 4

    def word(self, word):
        font = get_font(self.size, self.weight, self.style)
        if self.cursor_x + self.word_font.measure(word) > WIDTH - HSTEP:
            self.flush()
        self.line.append((self.cursor_x, word, self.word_font))
        self.cursor_x += self.word_font.measure(word) + self.word_font.measure(" ")
        

    def flush(self):
        if not self.line:
            return
        max_ascent = max([f.metrics("ascent") for x, word, f in self.line])
        baseline = self.cursor_y * 1.25 + max_ascent

        for x, word, f in self.line:
            y = baseline - f.metrics("ascent")
            self.display_list.append((x, y, word, f))

        max_descent = max(f.metrics("descent") for x, word, f in self.line)
        self.cursor_y = baseline + max_descent * 1.25
        self.cursor_x = HSTEP 
        self.line = []

class Browser:
    def __init__(self):
        self.window = tkinter.Tk()
        self.canvas = tkinter.Canvas(self.window, width=WIDTH, height=HEIGHT)
        self.canvas.pack()
        self.display_list = []
        self.scroll = 0
        self.window.bind("<Up>", self.scrollup)
        self.window.bind("<Down>", self.scrolldown)

        # print("fonts: ", font.families())
        self.bi_times = font.Font(
            family="Times",
            size=16,
            weight="bold",
            slant="italic",
        )

    def scrollup(self, e):
        self.scroll -= SCROLL_STEP
        self.draw()

    def scrolldown(self, e):
        self.scroll += SCROLL_STEP
        self.draw()

    def draw(self):
        self.canvas.delete("all")
        for x, y, c, font in self.display_list:
            if y > (self.scroll - VSTEP) + HEIGHT:
                continue
            if y + (VSTEP * 2) < self.scroll:
                continue
            self.canvas.create_text(
                x, y - (self.scroll), text=c, anchor="nw", font=font
            )

    def load(self, url):
        body = url.request()
        if url.scheme == "view-source":
            self.canvas.create_text(10, 10, text=body, anchor="nw")
        else:
            # print("body: ", body, "\n")
            tokens = lex(body)
            # print("text: ", text, "\n")
            self.display_list = Layout(tokens).display_list
            # print("self.display_list: ", self.display_list)
            self.draw()


class Text:
    def __init__(self, text):
        self.text = text


class Tag:
    def __init__(self, tag):
        self.tag = tag


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        url = URL(sys.argv[1])
        Browser().load(url)
    else:
        Browser().load(URL("file://" + DEFAULT_FILE))

    tkinter.mainloop()
