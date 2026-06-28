from css_parser import *
from html_parser import *
import urllib.parse
from url import URL
from tasks import *
import dukpy
import threading
from jscontext import JSContext

DEFAULT_STYLE_SHEET = CSSParser(open("browser.css").read()).parse()

class Tab:
    def __init__(self, browser, tab_height):
        self.history = []
        self.display_list = []
        self.scroll = 0
        self.url = None
        self.focus = None
        self.rules = []
        self.tab_height = tab_height

        self.task_runner = TaskRunner(self)
        self.task_runner_thread = threading.Thread(
            target=self.task_runner.run,
            daemon=True,
        )
        self.task_runner_thread.start()

        self.need_render = False
        self.browser = browser

    def scrollup(self):
        self.scroll = max(0, self.scroll - SCROLL_STEP)

    def scrolldown(self):
        max_y = max(self.document.height + 2 * VSTEP - self.tab_height, 0)
        self.scroll = min(self.scroll + SCROLL_STEP, max_y)

    def raster(self, canvas, offset):
        for cmd in self.display_list:
            if cmd.rect.top() > self.scroll + self.tab_height:
                continue
            if cmd.rect.bottom() < self.scroll:
                continue
            cmd.execute(self.scroll - offset, canvas)

    def set_needs_render(self):
        self.need_render = True

    def load(self, url, payload=None):
        headers, body = url.request(self.url, payload)
        self.history.append(url)
        self.url = url
        # print("html: ", body)

        self.allowed_origins = None
        if "content-security-policy" in headers:
            csp = headers["content-security-policy"].split()
            if len(csp) > 0 and csp[0] == "default-src":
                self.allowed_origins = []
                for origin in csp[1:]:
                    self.allowed_origins.append(URL(origin).origin())

        if url.scheme == "view-source":
            self.canvas.create_text(10, 10, text=body, anchor="nw")
        else:
            self.nodes = HTMLParser(body).parse()
            # print_tree(self.nodes)
            self.rules = DEFAULT_STYLE_SHEET.copy()
            scripts =  [node.attributes["src"] for node
                in tree_to_list(self.nodes, [])
                if isinstance(node, Element)
                and node.tag == "script"
                and "src" in node.attributes
            ]
            self.js = JSContext(self)
            print("Scripts: ", scripts)
            for script in scripts:
                script_url = url.resolve(script)
                # print("Loading script: ", script_url)
                if not self.allowed_request(script_url):
                    print("Blocked request: ", script, "due to cross-origin policy")
                    continue

                try:
                    header, script_body = script_url.request(script_url)
                    # print("Script body: ", script_body)
                except Exception as e:
                    print("Failed to load script: ", script_url, "Error:", e)  # ← print the error
                    continue
                task = Task(self.js.run, script_url, script_body)
                self.task_runner.schedule_task(task)
                # if self.js: self.js.discarded = True
                # self.js = JSContext(self)
                # result = self.js.run(script_url, script_body)
                # print("Script returned: ", result)

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
                    header, style_body = style_url.request(style_url)
                except Exception as e:
                    print("Failed to load script: ", style_url, "Error:", e)  # ← print the error
                    continue
                self.rules.extend(CSSParser(style_body).parse())
            self.set_needs_render()
            self.render()

        self.set_needs_render()

    def click(self, x, y):
        self.set_needs_render()
        self.render()
        # x, y = e.x, e.y
        self.focus = None

        y += self.scroll

        objs = [
            obj
            for obj in tree_to_list(self.document, [])
            if obj.x <= x < obj.x + obj.width and obj.y <= y < obj.y + obj.height
        ]

        if not objs:
            return
        elt = objs[-1].node

        while elt:
            if isinstance(elt, Text):
                pass
            elif elt.tag == "input":
                if self.js.dispatch_event("click", elt): return
                elt.attributes['value'] = ""
                if self.focus:
                    self.focus.is_focused = False
                self.focus = elt
                self.focus.is_focused = True
                self.set_needs_render()
                return self.render()
            elif elt.tag == "button":
                if self.js.dispatch_event("click", elt): return
                while elt:
                    if elt.tag == 'form' and "action" in elt.attributes:
                        return self.submit_form(elt)
                    elt = elt.parent
            elif elt.tag == "a" and "href" in elt.attributes:
                if self.js.dispatch_event("click", elt): return
                url = self.url.resolve(elt.attributes["href"])
                return self.load(url)
            elt = elt.parent

    def submit_form(self, elt):
        if self.js.dispatch_event("submit", elt): return
        inputs = [node for node in tree_to_list(elt, []) 
                if isinstance(node, Element) and node.tag == "input" and "name" in node.attributes]

        body = ""
        for input in inputs:
            name = input.attributes["name"]
            value = input.attributes.get("value", "")
            name = urllib.parse.quote(name)
            value = urllib.parse.quote(value)
            body += f"&{name}={value}"
        body = body[1:]

        url = self.url.resolve(elt.attributes["action"])
        self.load(url, body)

    def go_back(self):
        if len(self.history) > 1:
            self.history.pop()
            back = self.history.pop()
            self.load(back)

    def render(self):
        if not self.need_render: return
        style(self.nodes, sorted(self.rules, key=cascade_priority))
        self.document = DocumentLayout(self.nodes)
        self.document.layout()
        self.display_list = []
        paint_tree(self.document, self.display_list)
        self.need_render = False
        self.browser.set_needs_raster_and_draw()

    def keypress(self, char):
        if self.focus:
            if self.js.dispatch_event("keydown", self.focus): return
            if self.focus.tag == "input":
                self.focus.attributes["value"] = (
                    self.focus.attributes.get("value", "") + char
                )
                self.set_needs_render()
                self.render()

    def allowed_request(self, url):
        return self.allowed_origins == None or url.origin() in self.allowed_origins

