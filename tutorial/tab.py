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
    def __init__(
            self, 
            url, 
            scroll, 
            height, 
            display_list
        ):
        self.url = url
        self.scroll = scroll
        self.height = height
        self.display_list = display_list

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
        self.scroll_changed_in_tab = False

    def run_animation_frame(self, scroll):
        if scroll is None:
            scroll = self.scroll
        if not self.scroll_changed_in_tab:
            self.scroll = scroll
        self.js.interp.evaljs("__runRAFHandlers()")
        self.render()
        scroll = None
        if self.scroll_changed_in_tab:
            scroll = self.scroll
        print("run_animation_frame: ", f"self.url: {self.url}, scroll: {scroll}, self.document.height: {self.document.height}, self.display_list: {self.display_list}")
        commit_data = CommitData(
            self.url,
            scroll,
            self.document.height,
            self.display_list
        )
        self.display_list = None
        self.browser.commit(self, commit_data)
        self.scroll_changed_in_tab = False

    def scrollup(self):
        self.scroll = max(0, self.scroll - SCROLL_STEP)

    def scrolldown(self):
        max_y = max(self.document.height + 2 * VSTEP - self.tab_height, 0)
        self.scroll = min(self.scroll + SCROLL_STEP, max_y)

    def raster(self, canvas, offset):
        print("raster: ", f"self.display_list: {self.display_list.pop()}")
        if self.display_list is None: return
        for cmd in self.display_list:
            print("raster: ", f"self.scroll: {self.scroll}, self.tab_height: {self.tab_height}")
            if cmd.rect.top() > self.scroll + self.tab_height:
                continue
            if cmd.rect.bottom() < self.scroll:
                continue
            cmd.execute(self.scroll - offset, canvas)

    def set_needs_render(self):
        self.need_render = True
        self.browser.set_needs_animation_frame(self)

    def load(self, url, payload=None):
        print(f"Tab.load: Starting load for {url}")
        self.scroll = 0
        self.scroll_changed_in_tab = True

        headers, body = url.request(self.url, payload)
        self.history.append(url)
        self.url = url
        
        print(f"Loaded page, body length: {len(body)}")
        
        # ... CSP handling ...
        
        if url.scheme == "view-source":
            # Handle view-source
            pass
        else:
            self.nodes = HTMLParser(body).parse()
            print(f"Parsed HTML, nodes: {len(tree_to_list(self.nodes, []))} nodes")
            
            self.rules = DEFAULT_STYLE_SHEET.copy()
            
            # Create JS context
            self.js = JSContext(self)
            
            # Load scripts and stylesheets...
            # (existing code)
            
            # IMPORTANT: Force render immediately
            print("Forcing initial render")
            self.need_render = True
            self.render()
        
        self.set_needs_render()
        print("Tab.load: Completed")

    def clamp_scroll(self, scroll):
        height = math.ceil(self.document.height + 2*VSTEP)
        maxscroll = height - self.tab_height
        return max(0, min(scroll, maxscroll))

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
        if not self.need_render: 
            print("Render skipped - need_render is False")
            return
        
        print(f"Render starting for URL: {self.url}")
        
        if self.scroll is None:
            self.scroll = 0
            
        self.browser.measure.time("render")
        
        try:
            # Check if we have nodes to render
            if not self.nodes:
                print("No nodes to render!")
                self.display_list = []
                return
                
            self.js.interp.evaljs("__runRAFHandlers()")
            style(self.nodes, sorted(self.rules, key=cascade_priority))
            self.document = DocumentLayout(self.nodes)
            self.document.layout()
            self.display_list = []
            paint_tree(self.document, self.display_list)
            print(f"Render complete - display_list has {len(self.display_list)} items")
            
            clamped_scroll = self.clamp_scroll(self.scroll)
            if clamped_scroll != self.scroll:
                self.scroll_changed_in_tab = True
            self.scroll = clamped_scroll
        except Exception as e:
            print(f"Render error: {e}")
            import traceback
            traceback.print_exc()
            self.display_list = []
        finally:
            self.need_render = False
            self.browser.set_needs_raster_and_draw()
            self.browser.measure.stop("render")

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

