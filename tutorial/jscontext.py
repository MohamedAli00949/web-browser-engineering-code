import dukpy
import threading
from css_parser import *
from html_parser import *
from tasks import *

RUNTIME_JS = open("runtime.js").read()

EVENT_DISPATCH_JS = (
    "new window.Node(dukpy.handle).dispatchEvent(new window.Event(dukpy.type))"
)

POST_MESSAGE_DISPATCH_JS = "window.dispatchEvent(new window.MessageEvent(dukpy.data))"

SETTIMEOUT_JS = "__runSetTimeout(dukpy.handle)"
XHR_ONLOAD_JS = "__runXHROnload(dukpy.out, dukpy.handle)"


class JSContext:
    def __init__(self, tab, url_origin):
        self.tab = tab
        self.url_origin = url_origin

        self.interp = dukpy.JSInterpreter()
        self.interp.export_function("log", print)
        self.interp.export_function("querySelectorAll", self.querySelectorAll)
        self.interp.export_function("getAttribute", self.getAttribute)
        self.interp.export_function("innerHTML", self.innerHTML_set)
        self.interp.export_function("XMLHttpRequest_send", self.XMLHttpRequest_send)
        self.interp.export_function("setTimeout", self.setTimeout)
        self.interp.export_function("requestAnimationFrame", self.requestAnimationFrame)
        self.interp.export_function("style_set", self.style_set)
        self.interp.export_function("setAttribute", self.setAttribute)
        self.interp.export_function("parent", self.parent)
        self.interp.export_function("postMessage", self.postMessage)

        self.node_to_handle = {}
        self.handle_to_node = {}

        self.discarded = False

        self.interp.evaljs("function Window(id) { this._id = id; };")
        self.interp.evaljs("WINDOWS = {}")

    def throw_if_cross_origin(self, frame):
        if frame.url.origin() != self.url_origin:
            raise Exception("Cross-origin access disallowed from script")

    def add_window(self, frame):
        code = "var window_{} = new Window({});".format(
            frame.window_id, frame.window_id
        )
        self.interp.evaljs(code)

        self.tab.browser.measure.time("script-runtime")
        self.interp.evaljs(self.wrap(RUNTIME_JS, frame.window_id))
        self.tab.browser.measure.stop("script-runtime")

        self.interp.evaljs(
            "WINDOWS[{}] = window_{};".format(frame.window_id, frame.window_id)
        )

    def wrap(self, script, window_id):
        return "window = window_{}; {}".format(window_id, script)

    def run(self, script, code, window_id):
        try:
            code = self.wrap(code, window_id)
            self.tab.browser.measure.time("script-load")
            self.interp.evaljs(code)
            self.tab.browser.measure.stop("script-load")
        except dukpy.JSRuntimeError as e:
            self.tab.browser.measure.stop("script-load")
            print("Script: ", script, "crashed: ", e)

    def setAttribute(self, handle, attr, value, window_id):
        frame = self.tab.window_id_to_frame[window_id]
        self.throw_if_cross_origin(frame)
        elt = self.handle_to_node[handle]
        elt.attributes[attr] = value
        self.tab.set_needs_render_all_frames()

    def style_set(self, handle, s, window_id):
        frame = self.tab.window_id_to_frame[window_id]
        self.throw_if_cross_origin(frame)
        elt = self.handle_to_node[handle]
        elt.attributes["style"] = s
        frame.set_needs_render()

    def querySelectorAll(self, selector_text, window_id):
        frame = self.tab.window_id_to_frame[window_id]
        self.throw_if_cross_origin(frame)

        selector = CSSParser(selector_text).selector()
        nodes = [
            node for node in tree_to_list(frame.nodes, []) if selector.matches(node)
        ]

        return [self.get_handle(node) for node in nodes]

    def get_handle(self, elt):
        if elt not in self.node_to_handle:
            handle = len(self.node_to_handle)
            self.node_to_handle[elt] = handle
            self.handle_to_node[handle] = elt
        else:
            handle = self.node_to_handle[elt]
        return handle

    def getAttribute(self, handle, attr):
        elt = self.handle_to_node[handle]
        attr = elt.attributes.get(attr, None)
        return attr if attr else ""

    def dispatch_event(self, type, elt, window_id):
        handle = self.node_to_handle.get(elt, -1)
        try:
            code = self.wrap(EVENT_DISPATCH_JS, window_id)
            do_default = self.interp.evaljs(code, type=type, handle=handle)
        except dukpy.JSRuntimeError as e:
            print("JS error in dispatch_event:", e)
            return False  # allow default behavior to continue
        return not do_default

    def innerHTML_set(self, handle, s, window_id):
        frame = self.tab.window_id_to_frame[window_id]
        self.throw_if_cross_origin(frame)
        doc = HTMLParser("<html><body>" + s + "</body></html>").parse()
        new_nodes = doc.children[0].children

        elt = self.handle_to_node[handle]
        elt.children = new_nodes

        for child in elt.children:
            child.parent = elt

        frame.set_needs_render()

    def XMLHttpRequest_send(self, method, url, body, isasync, handle, window_id):
        frame = self.tab.window_id_to_frame[window_id]
        full_url = frame.url.resolve(url)

        if not frame.allowed_request(full_url):
            raise Exception("Cross-origin XML request blocked by CSP")

        if full_url.origin() != frame.url.origin():
            raise Exception("Cross-origin XML request not allowed")

        def run_load():
            headers, response = full_url.request(self.tab.url, body)
            response = response.decode("utf8", "replace")
            task = Task(self.dispatch_xhr_load, response, handle, window_id)
            self.tab.task_runner.schedule_task(task)
            if not isasync:
                return response

        if not isasync:
            return run_load()
        else:
            threading.Thread(target=run_load).start()

    def dispatch_xhr_onload(self, out, handle, window_id):
        self.tab.browser.measure.time("script-xhr")
        do_default = self.interp.evaljs(self.wrap(XHR_ONLOAD_JS, window_id), out=out, handle=handle)
        self.tab.browser.measure.stop("script-xhr")

    def setTimeout(self, handle, time, window_id):
        def run_callback():
            task = Task(self.dispatch_setimout, handle, window_id)
            self.tab.task_runner.schedule_task(task)

        threading.Timer(time / 1000.0, run_callback).start()

    def dispatch_setimout(self, handle, window_id):
        if self.discarded:
            return
        self.tab.browser.measure.time("script-settimeout")
        self.interp.evaljs(self.wrap(SETTIMEOUT_JS, window_id), handle=handle)
        self.tab.browser.measure.stop("script-settimeout")

    def requestAnimationFrame(self, callback):
        # task = Task(callback)
        # self.tab.task_runner.schedule_task(task)
        self.tab.browser.set_needs_animation_frame(self.tab)

    def dispatch_RAF(self, window_id):
        code = self.wrap("window.__runRAFHandlers()", window_id)
        self.interp.evaljs(code)

    def parent(self, window_id):
        parent_frame = self.tab.window_id_to_frame[window_id].parent_frame
        if parent_frame:
            return parent_frame.window_id
        else:
            return None

    def postMessage(self, target_window_id, message, origin):
        task = Task(self.tab.post_message, message, target_window_id)
        self.tab.task_runner.schedule_task(task)

    def dispatch_post_message(self, message, target_window_id):
        code = self.wrap(POST_MESSAGE_DISPATCH_JS, target_window_id)
        self.interp.evaljs(code, message=message)
