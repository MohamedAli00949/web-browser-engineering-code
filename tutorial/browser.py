import socket
import ssl
import os
import gzip

DEFAULT_FILE = "test/index.html"

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

class URL:
    socket_cache = {}

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
            cache_key = (self.host, self.port)

            s = URL.socket_cache.get(cache_key)

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
                URL.socket_cache.pop(cache_key, None)

                if redirect_url.startswith("/"):
                    redirect_url = f"{self.scheme}://{self.host}{redirect_url}"

                return URL(redirect_url).request(redirects=redirects+1)

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
                URL.socket_cache[cache_key] = s

            return content


def show(body):
    in_tag = False
    in_entity = False
    entity = ""

    for c in body:
        if in_entity:
            if c == ";":
                if entity == "lt":
                    print("<", end="")
                elif entity == "gt":
                    print(">", end="")
                else:
                    print("&" + entity + ";", end="")
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
            print(c, end="")


def load(url):
    body = url.request()
    if url.scheme == "view-source":
        print(body)
    else:
        show(body)

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        url = URL(sys.argv[1])
        load(url)
    else:
        load(URL("file://" + DEFAULT_FILE))
