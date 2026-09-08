from utils import *

class EmbedLayout:
    def __init__(self, node, parent, previous, frame):
        self.node = node
        self.frame = frame
        node.layout_object = self
        self.children = []
        self.parent = parent
        self.previous = previous

        self.x = None
        self.y = None
        self.width = None
        self.height = None
        self.font = None

    def layout(self):
        self.zoom = self.parent.zoom
        self.font = font(self.node.style, self.zoom)
        if self.previous:
            space = self.previous.font.measureText(" ")
            self.x = self.previous.x + space + self.previous.width
        else:
            self.x = self.parent.x

    def should_paint(self):
        return True
