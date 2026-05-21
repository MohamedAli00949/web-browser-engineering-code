import socket
import ssl

class URL:
  def __init__(self, url):
    self.schema, url = url.split("://", 1)
    # assert self.schema in ("http", "file", "data", "view-source")
    assert self.schema in ["http", "https"]
    
    if "/" not in url:
      url = url + "/"
    
    self.host, url = url.split("/", 1)
    self.path = "/" + url

    if ":" in self.host:
      self.host, self.port = self.host.split(":", 1)
      self.port = int(self.port)
    else:
      if self.schema == "https":
        self.port = 443
      else:
        self.port = 80
  
  def request(self):
    s = socket.socket(
      family=socket.AF_INET, 
      type=socket.SOCK_STREAM, 
      proto=socket.IPPROTO_TCP
    )
    s.connect((self.host, self.port))

    if self.schema == "https":
      ctx = ssl.create_default_context()
      s = ctx.wrap_socket(s, server_hostname=self.host)

    request = "GET {} HTTP/1.0\r\n".format(self.path)
    request += "Host: {}\r\n".format(self.host)
    request += "\r\n"
    s.send(request.encode("utf-8"))

    response = s.makefile("r", encoding="utf8", newline="\r\n")

    statusline = response.readline()
    version, status, explanation = statusline.split(" ", 2)

    response_headers = {}
    while True:
      line = response.readline()
      if line == "\r\n":
        break
      header, value = line.split(":", 1)
      response_headers[header.casefold()] = value.strip()
    
    assert "transfer-encoding" not in response_headers
    assert "content-encoding" not in response_headers

    content = response.read()
    return content


def show(body):
  in_tag = False
  for c in body:
    if c == "<":
      in_tag = True
    elif c == ">":
      in_tag = False
    elif not in_tag:
      print(c, end="")

def load(url):
  body = url.request()
  show(body)


if __name__ == "__main__":
  import sys
  url = URL(sys.argv[1])
  load(url)
