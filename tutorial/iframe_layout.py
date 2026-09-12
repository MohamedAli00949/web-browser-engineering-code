from embed_layout import *
from transform_effects import *
from paint_command import *


class IframeLayout(EmbedLayout):
    def __init__(self, node, parent, previous, parent_frame):
        super().__init__(node, parent, previous, parent_frame)

    def layout(self):  # done
        if not self.layout_needed(): return
        super().layout()

        width_attr = self.node.attributes.get("width")
        height_attr = self.node.attributes.get("height")

        w_zoom = self.zoom.read(notify=self.width)
        if width_attr:
            self.width.set(dpx(int(width_attr) + 2, w_zoom))
        else:
            self.width.set(dpx(IFRAME_WIDTH_PX + 2, w_zoom))

        zoom = self.zoom.read(notify=self.height)
        if height_attr:
            self.height.set(dpx(int(height_attr) + 2, zoom))
        else:
            self.height.set(dpx(IFRAME_HEIGHT_PX + 2, zoom))

        if self.node.frame and self.node.frame.loaded:
            self.node.frame.frame_height = self.height.get() - dpx(2, self.zoom.get())
            self.node.frame.frame_width = self.width.get() - dpx(2, self.zoom.get())
            self.node.frame.document.width.mark()

        height = self.height.read(notify=self.ascent)
        self.ascent.set(-height)
        self.descent.set(0)

    def paint(self):  # done
        cmds = []

        rect = skia.Rect.MakeLTRB(
            self.x.get(),
            self.y.get(),
            self.x.get() + self.width.get(),
            self.y.get() + self.height.get(),
        )
        bgcolor = self.node.style["background-color"].get()
        if bgcolor != "transparent":
            radius = dpx(
                float(self.node.style["border-radius"].get()[:-2]), self.zoom.get()
            )
            cmds.append(DrawRRect(rect, radius, bgcolor))
        return cmds

    def paint_effects(self, cmds):  # done
        rect = skia.Rect.MakeLTRB(
            self.x.get(),
            self.y.get(),
            self.x.get() + self.width.get(),
            self.y.get() + self.height.get(),
        )

        diff = dpx(1, self.zoom.get())
        offset = (self.x.get() + diff, self.y.get() + diff)
        cmds = [Transform(offset, rect, self.node, cmds)]
        inner_rect = skia.Rect.MakeLTRB(
            self.x.get() + diff,
            self.y.get() + diff,
            self.x.get() + self.width.get() - diff,
            self.y.get() + self.height.get() - diff,
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
        paint_outline(self.node, cmds, rect, self.zoom.get())
        cmds = paint_visual_effects(self.node, cmds, rect)

        return cmds
