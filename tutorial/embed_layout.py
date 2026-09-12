from utils import *
from protected_field import *


class EmbedLayout:
    def __init__(self, node, parent, previous, frame):  # done
        self.node = node
        self.frame = frame
        node.layout_object = self
        self.children = []
        self.parent = parent
        self.previous = previous

        self.zoom = ProtectedField(self, "zoom", self.parent, [self.parent.zoom])
        self.font = ProtectedField(
            self,
            "font",
            self.parent,
            [
                self.zoom,
                self.node.style["font-weight"],
                self.node.style["font-style"],
                self.node.style["font-size"],
            ],
        )
        self.width = ProtectedField(self, "width", self.parent, [self.zoom])
        self.height = ProtectedField(
            self, "height", self.parent, [self.zoom, self.font, self.width]
        )
        self.ascent = ProtectedField(self, "ascent", self.parent, [self.height])
        self.descent = ProtectedField(self, "descent", self.parent, [])

        if self.previous:
            x_dependencies = [self.previous.x, self.previous.font, self.previous.width]
        else:
            x_dependencies = [self.parent.x]
        self.x = ProtectedField(self, "x", self.parent, x_dependencies)
        self.y = ProtectedField(
            self, "y", self.parent, [self.ascent, self.parent.y, self.parent.ascent]
        )

        self.has_dirty_descendants = True

    def layout_needed(self):  # done
        if self.zoom.dirty:
            return True
        if self.width.dirty:
            return True
        if self.height.dirty:
            return True
        if self.x.dirty:
            return True
        if self.y.dirty:
            return True
        if self.ascent.dirty:
            return True
        if self.descent.dirty:
            return True
        if self.font.dirty:
            return True
        if self.has_dirty_descendants:
            return True
        return False

    def layout(self):  # done
        self.zoom.copy(self.parent.zoom)

        zoom = self.zoom.read(notify=self.font)
        self.font.set(font(self.node.style, zoom, notify=self.font))

        if self.previous:
            prev_x = self.previous.x.read(notify=self.x)
            prev_font = self.previous.font.read(notify=self.x)
            prev_width = self.previous.width.read(notify=self.x)
            self.x.set(prev_x + prev_font.measureText(" ") + prev_width)
        else:
            self.x.copy(self.parent.x)

        self.has_dirty_descendants = False

    def should_paint(self):
        return True
