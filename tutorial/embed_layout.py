from utils import *
from protected_field import *

class EmbedLayout:
    def __init__(self, node, parent, previous, frame):
        self.node = node
        self.frame = frame
        node.layout_object = self
        self.children = []
        self.parent = parent
        self.previous = previous

        self.x = ProtectedField()
        self.y = ProtectedField()
        self.width = ProtectedField()
        self.height = ProtectedField()
        self.font = ProtectedField()
        self.ascent = ProtectedField()
        self.descent = ProtectedField()

        self.zoom = ProtectedField()
        # self.parent.zoom.invalidations.add(self.zoom)

    def layout(self):
        self.zoom.copy(self.parent.zoom)

        zoom = self.zoom.read(notify=self.font)
        style = self.node.style.read(notify=self.font)
        self.font.set(font(style, zoom))

        if self.previous:
            prev_x = self.previous.x.read(notify=self.x)
            prev_font = self.previous.font.read(notify=self.x)
            prev_width = self.previous.width.read(notify=self.x)
            self.x.set(prev_x + prev_font.measureText(" ") + prev_width)
        else:
            self.x.copy(self.parent.x)

    def should_paint(self):
        return True
