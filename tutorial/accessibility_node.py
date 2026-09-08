from css_parser import *
from html_parser import *
from tasks import *


class AccessibilityNode:
    def __init__(self, node, parent=None):
        self.node = node
        self.children = []
        self.parent = parent
        self.text = ""
        self.bounds = self.compute_bounds()

        if isinstance(node, Text):
            if is_focusable(node.parent):
                self.role = "focusable text"
            else:
                self.role = "StaticText"
        else:
            if "role" in node.attributes:
                self.role = node.attributes["role"]
            elif node.tag == "a":
                self.role = "link"
            elif node.tag == "input":
                self.role = "textbox"
            elif node.tag == "button":
                self.role = "button"
            elif node.tag == "img":
                self.role = "image"
            elif node.tag == "html":
                self.role = "document"
            elif node.tag == "iframe":
                self.role = "iframe"
            elif is_focusable(node):
                self.role = "focusable"
            else:
                self.role = "none"

        self.bounds = self.compute_bounds()

    def compute_bounds(self):
        if self.node.layout_object:
            return [absolute_bounds_for_obj(self.node.layout_object)]

        if isinstance(self.node, Text):
            return []

        inline = self.node.parent
        bounds = []
        while not inline.layout_object:
            inline = inline.parent
        for line in inline.layout_object.children:
            line_bounds = skia.Rect.MakeEmpty()
            for child in line.children:
                if child.node.parent == self.node:
                    line_bounds.join(
                        skia.Rect.MakeXYWH(child.x, child.y, child.width, child.height)
                    )

            bounds.append(line_bounds)

        return bounds

    def build(self):
        for child_node in self.node.children:
            self.build_internal(child_node)

        if self.role == "StaticText":
            self.text = repr(self.node.text)
        elif self.role == "focusable text":
            self.text = "Focusable text:" + self.node.text
        elif self.role == "focusable":
            self.text = "Focusable element"
        elif self.role == "textbox":
            if "value" in self.node.attributes:
                value = self.node.attributes["value"]
            elif self.node.tag != "input" and self.node.children:
                isinstance(self.node.children[0], Text)
                value = self.node.children[0].text
            else:
                value = ""
            self.text = "Input box: " + value
        elif self.role == "button":
            self.text = "Button"
        elif self.role == "link":
            self.text = "Link"
        elif self.role == "alert":
            self.text = "Alert"
        elif self.role == "document":
            self.text = "Document"
        elif self.role == "image":
            if "alt" in self.node.attributes:
                self.text = "Image: " + self.node.attributes["alt"]
            else:
                self.text = "Image"
        elif self.role == "iframe":
            self.text = "Child document"

        if self.node.is_focused:
            self.text += " is focused"

    def build_internal(self, child_node):
        if (
            isinstance(child_node, Element)
            and child_node.tag == "iframe"
            and child_node.frame
            and child_node.frame.loaded
        ):
            child = FrameAccessibilityNode(child_node.frame.nodes)
        else:
            child = AccessibilityNode(child_node)

        if child.role != "none":
            self.children.append(child)
            child.build()
        else:
            for grandchild_node in child_node.children:
                child.build_internal(grandchild_node)

    def absolute_bounds(self):
        abs_bounds = []
        for bound in self.bounds:
            abs_bound = bound.makeOffset(0.0, 0.0)

            if isinstance(self, FrameAccessibilityNode):
                obj = self.parent
            else:
                obj = self
            
            while obj:
                obj.map_to_parent(abs_bound)
                obj = obj.parent
            abs_bounds.append(abs_bound)

        return abs_bounds


    def contains_point(self, x, y):
        for bound in self.bounds:
            if bound.contains(x, y):
                return True
        return False

    def hit_test(self, x, y):
        node = None
        if self.contains_point(x, y):
            node = self
        for child in self.children:
            res = child.hit_test(x, y)
            if res:
                node = res
        return node


class FrameAccessibilityNode(AccessibilityNode):
    def __init__(self, node, parent=None):
        super().__init__(node, parent)
        self.scroll = self.node.frame.scroll
        self.zoom = self.node.layout_object.zoom


    def build(self):
        self.build_internal(self.node.frame.nodes)

    def hit_test(self, x, y):
        bounds = self.bounds[0]
        if not bounds.contains(x, y): return
        new_x = x - bounds.left() - dpx(1, self.zoom)
        new_y = y - bounds.top() - dpx(1, self.zoom) + self.scroll
        node = self
        for child in self.children:
            res = child.hit_test(new_x, new_y)
            if res: node = res
        return node

