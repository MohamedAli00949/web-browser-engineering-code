from css_parser import *
from html_parser import *
import math
from accessibility_node import *
from frame import Frame


class CommitData:
    def __init__(
        self,
        url,
        scroll,
        root_frame_focused,
        height,
        display_list,
        composited_updates,
        accessibility_tree,
        focus,
    ):
        self.url = url
        self.scroll = scroll
        self.height = height
        self.display_list = display_list
        self.composited_updates = composited_updates
        self.accessibility_tree = accessibility_tree
        self.focus = focus
        self.root_frame_focused = root_frame_focused


class Tab:
    def __init__(self, browser, tab_height):
        self.history = []
        self.display_list = []
        self.scroll = 0
        self.url = None
        self.focus = None
        self.focused_frame = None
        self.tab_height = tab_height
        self.root_frame = None
        self.dark_mode = browser.dark_mode

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

        self.js = None  # diff
        self.zoom = 1.0
        self.needs_focus_scroll = False
        self.needs_accessibility = False
        self.accessibility_tree = None
        self.window_id_to_frame = {}

    def run_animation_frame(self, scroll):
        if not self.root_frame.scroll_changed_in_tab:
            self.root_frame.scroll = scroll

        need_composite = False

        for (window_id, frame) in self.window_id_to_frame.items():
            if not frame.loaded:
                continue

            self.browser.measure.time("script-runRAFHandlers")
            self.js.dispatch_RAF(frame.window_id)
            self.browser.measure.stop("script-runRAFHandlers")

            for node in tree_to_list(self.nodes, []):
                for (property_name, animation) in node.animations.items():
                    value = animation.animate()
                    if value:
                        node.style[property_name] = value
                        self.composited_updates.append(node)
                        self.set_needs_paint()

            need_composite = self.needs_style or self.needs_layout

        self.render()

        if self.focus and self.focused_frame.needs_focus_scroll:
            self.focused_frame.scroll_to(self.focus)
            self.focused_frame.needs_focus_scroll = False

        for (window_id, frame) in self.window_id_to_frame.items():
            if frame == self.root_frame:
                continue
            if frame.scroll_changed_in_frame:
                need_composite = True
                frame.scroll_changed_in_frame = False

        scroll = None
        if self.root_frame.scroll_changed_in_tab:
            scroll = self.root_frame.scroll

        composited_updates = None
        if not need_composite:
            composited_updates = {}
            for node in self.composited_updates:
                composited_updates[node] = node.blend_op
        self.composited_updates = []

        root_frame_focused = (
            not self.focused_frame or self.focused_frame == self.root_frame
        )
        commit_data = CommitData(
            self.url,
            scroll,
            root_frame_focused,
            math.ceil(self.root_frame.document.height),
            self.display_list,
            composited_updates,
            self.accessibility_tree,
            self.focus,
        )
        self.display_list = None
        self.root_frame.scroll_changed_in_tab = False

        self.browser.commit(self, commit_data)

    def scrollup(self):
        frame = self.focused_frame or self.root_frame
        frame.scrollup()
        self.needs_accessibility = True
        self.set_needs_paint()

    def scrolldown(self):
        frame = self.focused_frame or self.root_frame
        frame.scrolldown()
        self.needs_accessibility = True
        self.set_needs_paint()

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
            cmd.execute(canvas)

    def set_needs_render_all_frames(self):
        for id, frame in self.window_id_to_frame.items():
            frame.set_needs_render()

    def set_needs_paint(self):
        self.needs_paint = True
        self.browser.set_needs_animation_frame(self)

    def load(self, url, payload=None):
        print(f"Tab.load: Starting load for {url}")
        self.loaded = False

        self.history.append(url)

        self.task_runner.clear_pending_tasks()

        self.root_frame = Frame(self, None, None)
        self.root_frame.load(url, payload)

        self.root_frame.frame_width = WIDTH
        self.root_frame.frame_height = self.tab_height

        self.loaded = True
        print("Tab.load: Completed")

    def go_back(self):
        if len(self.history) > 1:
            self.history.pop()
            back = self.history.pop()
            self.load(back)

    def render(self):
        self.browser.measure.time("render")

        for id, frame in self.window_id_to_frame.items():
            if frame.loaded:
                frame.render()

        if self.needs_accessibility:
            self.accessibility_tree = AccessibilityNode(self.root_frame.nodes)
            self.accessibility_tree.build()
            print(self.accessibility_tree)
            self.needs_accessibility = False
            self.needs_paint = True

        if self.needs_paint:
            self.display_list = []
            paint_tree(self.root_frame.document, self.display_list)
            self.needs_paint = False

        self.browser.measure.stop("render")

    def click(self, x, y):
        self.render()
        self.root_frame.click(x, y)

    def keypress(self, char):
        frame = self.focused_frame
        if not frame:
            frame = self.root_frame
        frame.keypress(char)

    def set_dark_mode(self, val):
        self.dark_mode = val
        self.set_needs_render_all_frames()

    def enter(self):
        if not self.focus:
            return
        frame = self.focused_frame or self.root_frame
        frame.activate_element(self.focus)

    def advance_tab(self):
        frame = self.focused_frame or self.root_frame
        frame.advance_tab()

    def zoom_by(self, increment):
        if increment > 0:
            self.zoom *= 1.1
            self.scroll *= 1.1
        else:
            self.zoom *= 1 / 1.1
            self.scroll *= 1 / 1.1
        self.scroll_changed_in_tab = True
        self.set_needs_render_all_frames()

    def reset_zoom(self):
        self.scroll /= self.zoom
        self.zoom = 1
        self.scroll_changed_in_tab = True
        self.set_needs_render_all_frames()
