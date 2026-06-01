import socket
import ssl
import os
import gzip
import time


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
        return True, None

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
            cacheable = False
        elif directive not in ("public", "private", "must-revalidate"):
            cacheable = False

    return cacheable, max_age


class URL:
    socket_cache = {}
    response_cache = {}

    def __init__(self, url):
        if url.startswith("view-source:"):
            self.scheme = "view-source"
            self.inner_url = URL(url[len("view-source:"):])

            self.host = None
            self.port = None
            self.path = None

        elif url.startswith("data:"):
            self.scheme = "data"

            url = url[len("data:"):]
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

    def __str__(self):
        port_part = ":" + str(self.port)
        if self.scheme == "https" and self.port == 443:
            port_part = ""
        if self.scheme == "http" and self.port == 80:
            port_part = ""
        return self.scheme + "://" + self.host + port_part + self.path

    def request(self, payload=None, redirects=0):
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
            key = cache_key(self.scheme, self.host, self.path)
            if key in URL.response_cache and not payload:
                entry = URL.response_cache[key]
                if entry["expires"] is None or time.time() < entry["expires"]:
                    return entry["content"]
                else:
                    del URL.response_cache[key]

            socket_key = (self.host, self.port)
            method = "POST" if payload else "GET"

            # Never reuse a cached socket for POST requests
            if method == "POST":
                s = None
            else:
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

            # Build request headers and body, send in one call
            request = f"{method} {self.path} HTTP/1.1\r\n"
            request += f"Host: {self.host}\r\n"
            request += "Connection: close\r\n"
            request += "User-Agent: MoBrowserFromWebBrowserEngineeringBook/1.0\r\n"
            request += "Accept-Encoding: identity\r\n"

            if payload:
                payload_encoded = payload.encode("utf8")
                request += "Content-Type: application/x-www-form-urlencoded\r\n"
                request += f"Content-Length: {len(payload_encoded)}\r\n"
                request += "\r\n"
                s.send(request.encode("utf8") + payload_encoded)
            else:
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

            # Always close and remove from cache for POST, or if server requests it
            if response_headers.get("connection", "").lower() == "close" or method == "POST":
                s.close()
                URL.socket_cache.pop(socket_key, None)
            else:
                URL.socket_cache[socket_key] = s

            # Only cache GET 200 responses
            if status == "200" and method == "GET":
                cacheable, max_age = parse_cache_control(response_headers)
                if cacheable:
                    expires = (time.time() + max_age) if max_age is not None else None
                    URL.response_cache[key] = {"content": content, "expires": expires}

            return content

    def resolve(self, url):
        if "://" in url:
            return URL(url)
        if not url.startswith("/"):
            dir, _ = self.path.rsplit("/", 1)
            while url.startswith("../"):
                _, url = url.split("/", 1)
                if "/" in dir:
                    dir, _ = dir.rsplit("/", 1)
            url = dir + "/" + url

        if url.startswith("//"):
            return URL(f"{self.scheme}:{url}")
        else:
            return URL(f"{self.scheme}://{self.host}:{self.port}{url}")
