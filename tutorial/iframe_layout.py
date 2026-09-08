from embed_layout import *
from transform_effects import *
from paint_command import *


class IframeLayout(EmbedLayout):
    def __init__(self, node, parent, previous, parent_frame):
        super().__init__(node, parent, previous, parent_frame)

    def layout(self):
        super().layout()

        width_attr = self.node.attributes.get("width")
        height_attr = self.node.attributes.get("height")

        if width_attr:
            self.width = dpx(int(width_attr) + 2, self.zoom)
        else:
            self.width = dpx(IFRAME_WIDTH_PX + 2, self.zoom)

        if height_attr:
            self.height = dpx(int(height_attr) + 2, self.zoom)
        else:
            self.height = dpx(IFRAME_HEIGHT_PX + 2, self.zoom)

        if self.node.frame:
            self.node.frame.frame_height = self.height - dpx(2, self.zoom)
            self.node.frame.frame_width = self.width - dpx(2, self.zoom)

        self.ascent = -self.height
        self.descent = 0

    def paint(self):
        cmds = []

        rect = skia.Rect.MakeLTRB(
            self.x, self.y,
            self.x + self.width, self.y + self.height)
        bgcolor = self.node.style.get("background-color",
            "transparent")
        if bgcolor != "transparent":
            radius = dpx(float(
                self.node.style.get("border-radius", "0px")[:-2]),
                self.zoom)
            cmds.append(DrawRRect(rect, radius, bgcolor))
        return cmds

    def paint_effects(self, cmds):
        rect = skia.Rect.MakeLTRB(
            self.x, self.y, self.x + self.width, self.y + self.height
        )

        diff = dpx(1, self.zoom)
        offset = (self.x + diff, self.y + diff)
        cmds = [Transform(offset, rect, self.node, cmds)]
        inner_rect = skia.Rect.MakeLTRB(
            self.x + diff,
            self.y + diff,
            self.x + self.width - diff,
            self.y + self.height - diff,
        )
        internal_cmds = cmds
        internal_cmds.append(
            Blend(
                1.0,
                "destination-in",
                None,
                [DrawRRect(inner_rect, 0, "white")],
            )
        )
        cmds = [Blend(1.0, "source-over", self.node, internal_cmds)]
        paint_outline(self.node, cmds, rect, self.zoom)
        cmds = paint_visual_effects(self.node, cmds, rect)

        return cmds
