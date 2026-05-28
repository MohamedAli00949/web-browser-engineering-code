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
            key = cache_key(self.scheme, self.host, self.path)
            if key in URL.response_cache:
                entry = URL.response_cache[key]
                if entry["expires"] is None or time.time() < entry["expires"]:
                    return entry["content"]
                else:
                    del URL.response_cache[key]

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


class DocumentLayout:
    def __init__(self, node):
        self.node = node
        self.parent = None
        self.children = []

    def paint(self):
        return []

    def layout(self):
        self.width = WIDTH - 2 * HSTEP
        self.x = HSTEP
        self.y = VSTEP

        child = BlockLayout(self.node, self, None)
        self.children.append(child)
        child.layout()

        self.height = child.height


BLOCK_ELEMENTS = [
    "html",
    "body",
    "article",
    "section",
    "nav",
    "aside",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hgroup",
    "header",
    "footer",
    "address",
    "p",
    "hr",
    "pre",
    "blockquote",
    "ol",
    "ul",
    "menu",
    "li",
    "dl",
    "dt",
    "dd",
    "figure",
    "figcaption",
    "main",
    "div",
    "table",
    "form",
    "fieldset",
    "legend",
    "details",
    "summary",
]


class DrawText:
    def __init__(self, x1, y1, text, font, color):
        self.top = y1
        self.left = x1
        self.text = text
        self.font = font
        self.color = color

        self.bottom = y1 + font.metrics("linespace")

    def execute(self, scroll, canvas):
        canvas.create_text(
            self.left,
            self.top - scroll,
            text=self.text,
            font=self.font,
            anchor="nw",
            fill=self.color,
        )


class DrawRect:
    def __init__(self, x1, y1, x2, y2, color):
        self.top = y1
        self.left = x1
        self.bottom = y2
        self.right = x2
        self.color = color

    def execute(self, scroll, canvas):
        canvas.create_rectangle(
            self.left,
            self.top - scroll,
            self.right,
            self.bottom - scroll,
            width=0,
            fill=self.color,
        )


class TextLayout:
    def __init__(self, node, word, parent, previous):
        self.node = node
        self.word = word
        self.children = []
        self.parent = parent
        self.previous = previous

        self.font = None
        self.weight = 0
        self.style = "roman"
        self.size = 0
        self.height = 0
        self.x = 0
        self.y = 0

    def layout(self):
        weight = self.node.style["font-weight"]
        style = self.node.style["font-style"]
        if style == "normal":
            style = "roman"
        size = int(float(self.node.style["font-size"][:-2]) * 0.75)
        self.font = get_font(size, weight, style)
        self.width = self.font.measure(self.word)

        if self.previous:
            space = self.previous.font.measure(" ")
            self.x = self.previous.x + space + self.previous.width
        else:
            self.x = self.parent.x

        self.height = self.font.metrics("linespace")

    def paint(self):
        color = self.node.style["color"]
        return [DrawText(self.x, self.y, self.word, self.font, color)]

class LineLayout:
    def __init__(self, node, parent, previous):
        self.node = node
        self.parent = parent
        self.previous = previous
        self.children = []

        self.x = None
        self.y = None
        self.width = 0
        self.height = 0

    def layout(self):
        self.x = self.parent.x
        self.width = self.parent.width

        if self.previous:
            self.y = self.previous.y + self.previous.height
        else:
            self.y = self.parent.y

        for word in self.children:
            word.layout()

        # handle the line height
        if not self.children:
            self.height = 0
            return

        max_ascent = max(word.font.metrics("ascent") for word in self.children)
        baseline = self.y + 1.25 * max_ascent
        for word in self.children:
            word.y = baseline - word.font.metrics("ascent")
        max_descent = max(word.font.metrics("descent") for word in self.children)
        self.height = 1.25 * (max_ascent + max_descent)

    def paint(self):
        return []

class BlockLayout:
    def __init__(self, node, parent, previous):
        self.node = node
        self.parent = parent
        self.previous = previous
        self.children = []

        self.x = None
        self.y = None
        self.width = None
        self.height = None

        # self.line = []
        self.display_list = []
        self.weight = "normal"
        self.style = "roman"
        self.cursor_x, self.cursor_y = HSTEP, VSTEP
        self.size = 12
        self.word_font = font.Font(
            family="Times", size=self.size, weight=self.weight, slant=self.style
        )

        for child in self.children:
            child.layout()

    def paint(self):
        cmds = []

        bgcolor = self.node.style.get("background-color", "transparent")

        if bgcolor != "transparent":
            x2, y2 = self.x + self.width, self.y + self.height
            rect = DrawRect(self.x, self.y, x2, y2, bgcolor)
            cmds.append(rect)

        if self.layout_mode() == "inline":
            for x, y, word, font, color in self.display_list:
                cmds.append(DrawText(x, y, word, font, color))

        return cmds

    def layout(self):
        self.x = self.parent.x
        self.width = self.parent.width

        if self.previous:
            self.y = self.previous.y + self.previous.height
        else:
            self.y = self.parent.y

        mode = self.layout_mode()
        if mode == "block":
            previous = None
            for child in self.node.children:
                next = BlockLayout(child, self, previous)
                self.children.append(next)
                previous = next
            for child in self.children:
                child.layout()
        else:
            self.new_line()
            self.recurse(self.node)
            for line in self.children:
                line.layout()

        self.height = sum([child.height for child in self.children])

    def recurse(self, node):
        if isinstance(node, Text):
            for word in node.text.split():
                self.word(node, word)
        else:
            for child in node.children:
                self.recurse(child)

    def open_tag(self, tag):
        if tag == "i":
            self.style = "italic"
        elif tag == "b":
            self.weight = "bold"
        elif tag == "br":
            self.flush()
            self.cursor_x = HSTEP
            self.cursor_y += self.word_font.metrics("linespace") * 1.25
        elif tag == "p" or tag == "div":
            self.flush()
            self.cursor_y += VSTEP
        elif tag == "pre":
            self.style = "roman"
            self.cursor_x = HSTEP
            self.cursor_y += self.word_font.metrics("linespace") * 1.25
        # elif tag == "h1":
        #     self.flush()
        #     self.size += 20
        #     self.cursor_x = HSTEP
        #     self.cursor_y += self.word_font.metrics("linespace") * 3.5
        # elif tag == "h2":
        #     self.flush()
        #     self.size += 10
        #     self.cursor_x = HSTEP
        #     self.cursor_y += self.word_font.metrics("linespace") * 2.5
        # elif tag == "h3":
        #     self.flush()
        #     self.size += 5
        #     self.cursor_x = HSTEP
        #     self.cursor_y += self.word_font.metrics("linespace") * 1.75
        elif tag == "small":
            self.size -= 2
        elif tag == "big":
            self.size += 4

    def close_tag(self, tag):
        if tag == "i":
            self.style = "roman"
        elif tag == "b":
            self.weight = "normal"
        # elif tag == "h1":
        #     self.size -= 20
        # elif tag == "h2":
        #     self.size -= 10
        # elif tag == "h3":
        #     self.size -= 5
        elif tag == "small":
            self.size += 2
        elif tag == "big":
            self.size -= 4

    def new_line(self):
        self.cursor_x = 0
        last_line = self.children[-1] if self.children else None
        new_line = LineLayout(self.node, self, last_line)
        self.children.append(new_line)

    def word(self, node, word):
        line = self.children[-1]
        previous_word = line.children[-1] if line.children else None
        text = TextLayout(node, word, line, previous_word)
        line.children.append(text)

    def flush(self):
        if not self.line:
            return
        max_ascent = max([f.metrics("ascent") for x, word, f, color in self.line])
        baseline = self.cursor_y * 1.25 + max_ascent

        for rel_x, word, f, color in self.line:
            x = self.x + rel_x
            y = self.y + baseline - f.metrics("ascent")
            self.display_list.append((x, y, word, f, color))

        max_descent = max(f.metrics("descent") for _, _, f, _ in self.line)
        self.cursor_y = baseline + max_descent * 1.25
        self.cursor_x = HSTEP
        self.line = []

    def layout_intermediate(self):
        previous = None
        for child in self.node.children:
            next = BlockLayout(child, self, previous)
            self.children.append(next)
            previous = next

    def layout_mode(self):
        if isinstance(self.node, Text):
            return "inline"
        elif any(
            [
                isinstance(child, Element) and child.tag in BLOCK_ELEMENTS
                for child in self.node.children
            ]
        ):
            return "block"
        else:
            return "inline"


class Text:
    def __init__(self, text, parent):
        self.text = text
        self.children = []
        self.parent = parent

    def __repr__(self):
        return repr(self.text)


class Element:
    def __init__(self, tag, attributes, parent):
        self.tag = tag
        self.children = []
        self.parent = parent
        self.attributes = attributes

    def __repr__(self):
        return "<" + self.tag + ">"


def print_tree(node, indent=0):
    print(" " * indent, node)
    for child in node.children:
        print_tree(child, indent + 2)


def paint_tree(layout_object, display_list):
    display_list.extend(layout_object.paint())

    for child in layout_object.children:
        paint_tree(child, display_list)


class CSSParser:
    def __init__(self, s):
        self.s = s
        self.i = 0

    def whitespace(self):
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def word(self):
        start = self.i
        while self.i < len(self.s):
            if self.s[self.i].isalnum() or self.s[self.i] in "#-.%":
                self.i += 1
            else:
                break
        if not (self.i > start):
            raise Exception("Parsing error")
        return self.s[start : self.i]

    def literal(self, literal):
        if not (self.i < len(self.s)) and self.s[self.i] == literal:
            raise Exception("Parsing error")
        self.i += 1

    def pair(self):
        prop = self.word()
        self.whitespace()
        self.literal(":")
        self.whitespace()
        value = self.word()
        return prop.casefold(), value

    def body(self):
        pairs = {}
        while self.i < len(self.s) and self.s[self.i] != "}":
            try:
                prop, value = self.pair()
                pairs[prop.casefold()] = value
                self.whitespace()
                self.literal(";")
                self.whitespace()
            except Exception:
                why = self.ignore_until([";", "}"])
                if why == ";":
                    self.literal(";")
                    self.whitespace()
                else:
                    break
        return pairs

    def ignore_until(self, chars):
        while self.i < len(self.s):
            if self.s[self.i] in chars:
                return self.s[self.i]
            else:
                self.i += 1
        return None

    def selector(self):
        out = TagSelector(self.word().casefold())
        self.whitespace()
        while self.i < len(self.s) and self.s[self.i] != "{":
            tag = self.word()
            descendant = TagSelector(tag.casefold())
            out = DescendantSelector(out, descendant)
            self.whitespace()
        return out

    def parse(self):
        rules = []
        while self.i < len(self.s):
            try:
                self.whitespace()
                selector = self.selector()
                self.literal("{")
                self.whitespace()
                body = self.body()
                self.literal("}")
                rules.append((selector, body))
            except Exception:
                why = self.ignore_until(["}"])
                if why == ";":
                    self.literal(";")
                    self.whitespace()
                else:
                    break
        return rules


INHERITED_PROPERTIES = {
    "font-size": "16px",
    "font-style": "normal",
    "font-weight": "normal",
    "color": "black",
}


def style(node, rules):
    node.style = {}

    for property, default_value in INHERITED_PROPERTIES.items():
        if node.parent:
            node.style[property] = node.parent.style[property]
        else:
            node.style[property] = default_value

    for selector, body in rules:
        if not selector.matches(node):
            continue
        for property, value in body.items():
            node.style[property] = value

    if isinstance(node, Element) and "style" in node.attributes:
        pairs = CSSParser(node.attributes["style"]).body()
        for prop, value in pairs.items():
            node.style[prop] = value

    if node.style["font-size"].endswith("%"):
        # print("node: ", node, node.style)
        if node.parent:
            parent_font_size = node.parent.style["font-size"]
        else:
            parent_font_size = INHERITED_PROPERTIES["font-size"]
        node_pct = float(node.style["font-size"][:-1]) / 100
        parent_px = float(parent_font_size[:-2])
        node.style["font-size"] = str(node_pct * parent_px) + "px"

    for child in node.children:
        style(child, rules)

class TagSelector:
    def __init__(self, tag):
        self.tag = tag
        self.priority = 1

    def matches(self, node):
        return isinstance(node, Element) and node.tag == self.tag


class DescendantSelector:
    def __init__(self, ancestor, descendant):
        self.ancestor = ancestor
        self.descendant = descendant
        self.priority = ancestor.priority + descendant.priority

    def matches(self, node):
        if not self.descendant.matches(node):
            return False
        while node.parent:
            if self.ancestor.matches(node.parent):
                return True
            node = node.parent
        return False


class HTMLParser:
    def __init__(self, body):
        self.body = body
        self.unfinished = []

    SELF_CLOSING_TAGS = [
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    ]

    HEAD_TAGS = [
        "base",
        "basefont",
        "bgsound",
        "noscript",
        "link",
        "meta",
        "title",
        "style",
        "script",
    ]

    def parse(self):
        text = ""
        in_tag = False

        for c in self.body:
            if c == "<":
                in_tag = True
                if text:
                    self.add_text(text)
                text = ""
            elif c == ">":
                in_tag = False
                self.add_tag(text)
                text = ""
            else:
                text += c

        if not in_tag and text:
            self.add_text(text)

        return self.finish()

    def finish(self):
        if not self.unfinished:
            self.implicit_tags(None)

        while len(self.unfinished) > 1:
            node = self.unfinished.pop()
            parent = self.unfinished[-1]
            parent.children.append(node)

        return self.unfinished.pop()

    def implicit_tags(self, tag):
        while True:
            open_tags = [node.tag for node in self.unfinished]
            if open_tags == [] and tag != "html":
                self.add_tag("html")
            elif open_tags == ["html"] and tag not in ["/html", "head", "body"]:
                if tag in self.HEAD_TAGS:
                    self.add_tag("head")
                else:
                    self.add_tag("body")
            elif (
                open_tags == ["html", "head"] and tag not in ["/head"] + self.HEAD_TAGS
            ):
                self.add_tag("/head")
            else:
                break

    def add_text(self, text):
        if text.isspace():
            return
        self.implicit_tags(None)
        parent = self.unfinished[-1] if self.unfinished else None
        node = Text(text, parent)
        parent.children.append(node)

    def add_tag(self, tag):
        tag, attributes = self.get_attributes(tag)
        if tag.startswith("!"):
            return

        self.implicit_tags(tag)

        if tag.startswith("/"):
            if len(self.unfinished) == 1:
                return
            node = self.unfinished.pop()
            parent = self.unfinished[-1]
            parent.children.append(node)
        elif tag in self.SELF_CLOSING_TAGS:
            parent = self.unfinished[-1]
            node = Element(tag, attributes, parent)
            parent.children.append(node)
        else:
            parent = self.unfinished[-1] if self.unfinished else None
            node = Element(tag, attributes, parent)
            self.unfinished.append(node)

    def get_attributes(self, text):
        parts = text.split()
        tag = parts[0].casefold()
        attributes = {}

        for attrpair in parts[1:]:
            if "=" in attrpair:
                key, value = attrpair.split("=", 1)
                if len(value) > 2 and value[0] in ["'", '"']:
                    value = value[1:-1]
                attributes[key.casefold()] = value
            else:
                attributes[attrpair.casefold()] = ""

        return tag, attributes


DEFAULT_STYLE_SHEET = CSSParser(open("browser.css").read()).parse()


def tree_to_list(tree, list):
    list.append(tree)
    for child in tree.children:
        tree_to_list(child, list)

    return list


def cascade_priority(rule):
    selector, body = rule
    return selector.priority


class Browser:
    def __init__(self):
        self.window = tkinter.Tk()
        self.canvas = tkinter.Canvas(self.window, width=WIDTH, height=HEIGHT, bg="white")
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
        self.scroll = max(0, self.scroll - SCROLL_STEP)
        self.draw()

    def scrolldown(self, e):
        max_y = max(self.document.height + 2 * VSTEP - HEIGHT, 0)
        self.scroll = min(self.scroll + SCROLL_STEP, max_y)
        self.draw()

    def draw(self):
        self.canvas.delete("all")
        for cmd in self.display_list:
            if cmd.top > self.scroll + HEIGHT:
                continue
            if cmd.bottom < self.scroll:
                continue
            cmd.execute(self.scroll, self.canvas)

    def load(self, url):
        body = url.request()
        if url.scheme == "view-source":
            self.canvas.create_text(10, 10, text=body, anchor="nw")
        else:
            self.nodes = HTMLParser(body).parse()
            # print_tree(self.nodes)
            rules = DEFAULT_STYLE_SHEET.copy()
            links = [
                node.attributes["href"]
                for node in tree_to_list(self.nodes, [])
                if isinstance(node, Element)
                and node.tag == "link"
                and node.attributes["rel"] == "stylesheet"
                and "href" in node.attributes
            ]
            for link in links:
                style_url = url.resolve(link)
                try:
                    style_body = style_url.request()
                except:
                    continue
                rules.extend(CSSParser(style_body).parse())
            style(self.nodes, sorted(rules, key=cascade_priority))
            self.document = DocumentLayout(self.nodes)
            self.document.layout()
            self.display_list = []
            paint_tree(self.document, self.display_list)
            self.draw()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        url = URL(sys.argv[1])
        Browser().load(url)
    else:
        Browser().load(URL("file://" + DEFAULT_FILE))

    tkinter.mainloop()
