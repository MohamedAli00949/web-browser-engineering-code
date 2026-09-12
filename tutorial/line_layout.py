from embed_layout import *
from line_layout import *
from transform_effects import *
from paint_command import *
from protected_field import *


class LineLayout:
    def __init__(self, node, parent, previous):
        self.node = node
        self.parent = parent
        self.previous = previous
        self.children = []

        self.x = ProtectedField()
        self.y = ProtectedField()
        self.width = ProtectedField()
        self.height = ProtectedField()

        self.ascent = ProtectedField()
        self.descent = ProtectedField()

        self.zoom = ProtectedField()
        self.parent.zoom.invalidations.add(self.zoom)

    def layout(self):
        self.zoom.copy(self.parent.zoom)
        self.width.copy(self.parent.width)
        self.x.copy(self.parent.x)

        if self.previous:
            prev_y = self.previous.y.read(notify=self.y)
            prev_height = self.previous.height.read(notify=self.y)
            self.y.set(prev_y + prev_height)
        else:
            self.y.copy(self.parent.y)

        for word in self.children:
            word.layout()

        if not self.children:
            self.ascent.set(0)
            self.descent.set(0)
            self.height.set(0)
            return

        self.ascent.set(max([
            -child.ascent.read(notify=self.ascent)
            for child in self.children
        ]))

        self.descent.set(max([
            child.descent.read(notify=self.descent)
            for child in self.children
        ]))

        for child in self.children:
            new_y = self.y.read(notify=child.y)
            new_y += self.ascent.read(notify=child.y)
            if isinstance(child, TextLayout):
                new_y += child.ascent.read(notify=child.y) / 1.25
            else:
                new_y += child.ascent.read(notify=child.y)
            child.y.set(new_y)

        max_ascent = self.ascent.read(notify=self.height)
        max_descent = self.descent.read(notify=self.height)

        self.height.set(max_ascent + max_descent)

    def paint(self):
        return []

    def should_paint(self):
        return True

    def paint_effects(self, cmds):
        outline_rect = skia.Rect.MakeEmpty()
        outline_node = None
        for child in self.children:
            outline_str = child.node.parent.style["outline"].get()
            if parse_outline(outline_str):
                outline_rect.join(child.self_rect())
                outline_node = child.node.parent

        if outline_node:
            paint_outline(outline_node, cmds, outline_rect, self.zoom.get())
        return cmds

class TextLayout:
    def __init__(self, node, word, parent, previous):
        self.node = node
        self.word = word
        self.children = []
        self.parent = parent
        self.previous = previous

        self.font = ProtectedField()
        self.ascent = ProtectedField()
        self.descent = ProtectedField()
        self.weight = 0
        self.style = "roman"
        self.size = 0
        self.width = ProtectedField()
        self.height = ProtectedField()
        self.x = ProtectedField()
        self.y = ProtectedField()

        self.zoom = ProtectedField()
        # self.parent.zoom.invalidations.add(self.zoom)

    def layout(self):
        self.zoom.copy(self.parent.zoom)

        zoom = self.zoom.read(notify=self.font)
        style = self.node.style.read(notify=self.font)
        self.font.set(font(style, zoom))

        f = self.font.read(notify=self.width)
        self.width.set(f.measureText(self.word))

        f = self.font.read(notify=self.ascent)
        self.ascent.set(f.getMetrics().fAscent * 1.25)

        f = self.font.read(notify=self.descent)
        self.descent.set(f.getMetrics().fDescent * 1.25)

        f = self.font.read(notify=self.height)
        self.height.set(linespace(f) * 1.25)

        if self.previous:
            prev_x = self.previous.x.read(notify=self.x)
            prev_font = self.previous.font.read(notify=self.x)
            prev_width = self.previous.width.read(notify=self.x)
            self.x.set(prev_x + prev_font.measureText(" ") + prev_width)
        else:
            self.x.copy(self.parent.x)

    def self_rect(self):
        return skia.Rect.MakeLTRB(
            self.x, self.y, self.x + self.width, self.y + self.height
        )

    def paint(self):
        color = self.node.style["color"]
        return [DrawText(self.x, self.y, self.word, self.font, color)]

    def should_paint(self):
        return True

    def paint_effects(self, cmds):
        return cmds
