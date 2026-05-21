import socket
import ssl
import os

DEFAULT_FILE = "test/index.html"

class URL:
    def __init__(self, url):
        if url.startswith("view-source:"):
            self.scheme = "view-source"
            self.inner_url = URL(url[len("view-source:"):])  # parse the inner URL recursively
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
            # assert self.scheme in ("http", "file", "data", "view-source")
            assert self.scheme in ["http", "https", "file"]

            if self.scheme == "file":
                # On Windows, file:///D:/path → url = /D:/path
                # Strip the leading slash before a drive letter (e.g. /D:/)
                if (
                    os.name == "nt"
                    and url.startswith("/")
                    and len(url) > 2
                    and url[2] == ":"
                ):
                    url = url[1:]  # remove the leading slash
                self.path = url
                self.host = None
                self.port = None
            else:
                if "/" not in url:
                    url = url + "/"

                self.host, url = url.split("/", 1)
                self.path = "/" + url

                if ":" in self.host:
                    self.host, self.port = self.host.split(":", 1)
                    self.port = int(self.port)
                else:
                    if self.scheme == "https":
                        self.port = 443
                    else:
                        self.port = 80

    def request(self):
        if self.scheme == "view-source":
            return self.inner_url.request()  # fetch normally, just return raw body
        if self.scheme == "data":
            if self.mimetype == "text/html" or self.mimetype == "text/plain":
                return self.data
            else:
                return f"<p>Unsupported data type: {self.mimetype}</p>"
        elif self.scheme == "file":
            with open(self.path, "r") as f:
                return f.read()
        else:
            s = socket.socket(
                family=socket.AF_INET, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
            )
            s.connect((self.host, self.port))

            if self.scheme == "https":
                ctx = ssl.create_default_context()
                s = ctx.wrap_socket(s, server_hostname=self.host)

            request_headers = {
                "Host": self.host,
                "Connection": "close",
                "User-Agent": "MoBrowserFromWebBrowserEngineeringBook/1.0",
            }

            request = "GET {} HTTP/1.1\r\n".format(self.path)
            for header, value in request_headers.items():
                request += "{}: {}\r\n".format(header, value)
            request += "\r\n"
            s.send(request.encode("utf-8"))

            response = s.makefile("r", encoding="utf8", newline="\r\n")

            statusLine = response.readline()
            version, status, explanation = statusLine.split(" ", 2)

            response_headers = {}
            while True:
                line = response.readline()
                if line == "\r\n":
                    break
                header, value = line.split(":", 1)
                response_headers[header.casefold()] = value.strip()

            # assert "transfer-encoding" not in response_headers
            assert "content-encoding" not in response_headers

            content = response.read()
            return content


def show(body):
    in_tag = False
    in_entity = False
    entity = ""

    for c in body:
        if in_entity:
            if c == ";":
                # resolve the entity
                if entity == "lt":
                    print("<", end="")
                elif entity == "gt":
                    print(">", end="")
                else:
                    print("&" + entity + ";", end="")
                in_entity = False
                entity = ""
            else:
                entity += c  # keep accumulating entity name
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
        print(body)  # print raw HTML source as-is
    else:
        show(body)   # strip tags and print text

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        url = URL(sys.argv[1])
        load(url)
    else:
        load(URL("file://" + DEFAULT_FILE))
