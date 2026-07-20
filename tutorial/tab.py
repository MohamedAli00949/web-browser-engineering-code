from css_parser import *
from html_parser import *
import urllib.parse
from url import URL
from tasks import *
import dukpy
import threading
from jscontext import JSContext
import math

DEFAULT_STYLE_SHEET = CSSParser(open("browser.css").read()).parse()


class CommitData:
    def __init__(self, url, scroll, height, display_list, composited_updates):
        self.url = url
        self.scroll = scroll
        self.height = height
        self.display_list = display_list
        self.composited_updates = composited_updates


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
        self.task_runner.start_thread()

        self.need_render = False
        self.needs_style = False
        self.needs_layout = False
        self.needs_paint = False
        self.loaded = False
        self.browser = browser
        self.scroll_changed_in_tab = False
        self.composited_updates = []

        self.js = None

    def run_animation_frame(self, scroll):
        if not self.scroll_changed_in_tab:
            self.scroll = scroll
        self.browser.measure.time("script-runRAFHandlers")
        self.js.interp.evaljs("__runRAFHandlers()")
        self.browser.measure.stop("script-runRAFHandlers")

        for node in tree_to_list(self.document, []):
            for property_name, animation in node.animations.items():
                value = animation.animate()
                if value:
                    node.style[property_name] = value
                    self.composited_updates.append(node)
                    self.set_needs_paint()

        need_composite = self.needs_style or self.needs_layout

        self.render()

        scroll = None
        if self.scroll_changed_in_tab:
            scroll = self.scroll

        composited_updates = None
        if not need_composite:
            composited_updates = {}
            for node in self.composited_updates:
                composited_updates[node] = node.blend_op
        self.composited_updates = []

        document_height = math.ceil(self.document.height + 2 * VSTEP)
        commit_data = CommitData(
            self.url, scroll, document_height, 
            self.display_list, 
            composited_updates
        )
        self.display_list = None
        self.scroll_changed_in_tab = False

        self.browser.commit(self, commit_data)

    def scrollup(self):
        max_y = max(self.document.height + 2 * VSTEP + self.tab_height, 0)
        self.scroll = max(max_y, self.scroll - SCROLL_STEP)

    def scrolldown(self):
        max_y = max(self.document.height + 2 * VSTEP - self.tab_height, 0)
        self.scroll = min(self.scroll + SCROLL_STEP, max_y)

    def raster(self, canvas, offset):
        print("raster: ", f"self.display_list: {self.display_list.pop()}")
        if self.display_list is None:
            return
        for cmd in self.display_list:
            print(
                "raster: ",
                f"self.scroll: {self.scroll}, self.tab_height: {self.tab_height}",
            )
            if cmd.rect.top() > self.scroll + self.tab_height:
                continue
            if cmd.rect.bottom() < self.scroll:
                continue
            cmd.execute(self.scroll - offset, canvas)

    def set_needs_render(self):
        self.needs_style = True
        self.browser.set_needs_animation_frame(self)

    def set_needs_layout(self):
        self.needs_layout = True
        self.browser.set_needs_animation_frame(self)

    def set_needs_paint(self):
        self.needs_paint = True
        self.browser.set_needs_animation_frame(self)

    def load(self, url, payload=None):
        print(f"Tab.load: Starting load for {url}")
        self.loaded = False
        self.scroll = 0
        self.scroll_changed_in_tab = True
        self.task_runner.clear_pending_tasks()

        headers, body = url.request(self.url, payload)
        self.url = url
        self.history.append(url)

        print(f"Loaded page, body length: {len(body)}")

        self.allowed_origins = None
        if "content-security-policy" in headers:
            csp = headers["content-security-policy"].split()
            if len(csp) > 0 and csp[0] == "default-src":
                self.allowed_origins = csp[1:]

        self.nodes = HTMLParser(body).parse()
        print(f"Parsed HTML, nodes: {len(tree_to_list(self.nodes, []))} nodes")

        if self.js:
            self.js.discarded = True
        self.js = JSContext(self)
        scripts = [
            node.attributes["src"]
            for node in tree_to_list(self.nodes, [])
            if isinstance(node, Element)
            and node.tag == "script"
            and "src" in node.attributes
        ]
        for script in scripts:
            script_url = url.resolve(script)
            if not self.allowed_request(script_url):
                print("Blocked script load:", script_url)
                continue

            try:
                headers, body = script_url.request(self.url, None)
                self.js.run(script_url, body)
            except dukpy.JSRuntimeError as e:
                print("Script: ", script, "crashed: ", e)
                continue

        self.rules = DEFAULT_STYLE_SHEET.copy()

        links = [
            node.attributes["href"]
            for node in tree_to_list(self.nodes, [])
            if isinstance(node, Element)
            and node.tag == "link"
            and node.attributes.get("rel") == "stylesheet"
            and "href" in node.attributes
        ]

        for link in links:
            style_url = url.resolve(link)
            if not self.allowed_request(style_url):
                print("Blocked style", link, "due to CSP")
                continue
            try:
                header, body = style_url.request(url)
            except:
                continue
            self.rules.extend(CSSParser(body).parse())

        self.set_needs_render()
        self.loaded = True
        print("Tab.load: Completed")

    def clamp_scroll(self, scroll):
        height = math.ceil(self.document.height + 2 * VSTEP)
        maxscroll = height - self.tab_height
        return max(0, min(scroll, maxscroll))

    def click(self, x, y):
        self.render()
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

        if elt and self.js.dispatch_event("click", elt):
            return

        while elt:
            if isinstance(elt, Text):
                pass
            elif elt.tag == "a" and "href" in elt.attributes:
                url = self.url.resolve(elt.attributes["href"])
                self.load(url)
                return
            elif elt.tag == "input":
                elt.attributes["value"] = ""
                if self.focus:
                    self.focus.is_focused = False
                self.focus = elt
                elt.is_focused = True
                self.set_needs_render()
                return
            elif elt.tag == "button":
                while elt.parent:
                    if elt.tag == "form" and "action" in elt.attributes:
                        return self.submit_form(elt)
                    elt = elt.parent
            elt = elt.parent

    def submit_form(self, elt):
        if self.js.dispatch_event("submit", elt):
            return
        inputs = [
            node
            for node in tree_to_list(elt, [])
            if isinstance(node, Element)
            and node.tag == "input"
            and "name" in node.attributes
        ]

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
        if not self.need_render:
            return
        self.browser.measure.time("render")

        if self.needs_style:
            style(self.nodes, sorted(self.rules, key=cascade_priority))
            self.needs_layout = True
            self.needs_style = False

        if self.needs_layout:
            self.document = DocumentLayout(self.nodes)
            self.document.layout()
            self.needs_paint = True
            self.needs_layout = False

        if self.needs_paint:
            self.display_list = []
            paint_tree(self.document, self.display_list)
            self.needs_paint = False

        clamped_scroll = self.clamp_scroll(self.scroll)
        if clamped_scroll != self.scroll:
            self.scroll_changed_in_tab = True
        self.scroll = clamped_scroll

        self.browser.measure.stop("render")

        # for item in self.display_list:
        #     print_tree(item)

    def keypress(self, char):
        if self.focus:
            if self.js.dispatch_event("keydown", self.focus):
                return
            if self.focus.tag == "input":
                self.focus.attributes["value"] = (
                    self.focus.attributes.get("value", "") + char
                )
                self.set_needs_render()
                # self.render()

    def allowed_request(self, url):
        return self.allowed_origins == None or url.origin() in self.allowed_origins
