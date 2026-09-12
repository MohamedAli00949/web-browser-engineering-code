import skia
from utils import *
from paint_command import *


class VisualEffect:
    def __init__(self, rect, children, node=None):
        self.rect = rect.makeOffset(0.0, 0.0)
        self.children = children
        for child in self.children:
            self.rect.join(child.rect)
        self.node = node
        self.needs_compositing = any(
            [
                child.needs_compositing
                for child in self.children
                if isinstance(child, VisualEffect)
            ]
        )


class Blend(VisualEffect):
    def __init__(self, opacity, blend_mode, node, children):
        super().__init__(
            skia.Rect.MakeEmpty(),
            children,
            node,
        )
        self.opacity = opacity
        self.blend_mode = blend_mode
        self.should_save = self.blend_mode or self.opacity < 1
        if self.should_save:
            self.needs_compositing = True
        self.children = children
        self.rect = skia.Rect.MakeEmpty()
        for cmd in self.children:
            self.rect.join(cmd.rect)

    def execute(self, canvas):
        paint = skia.Paint(
            Alphaf=self.opacity, BlendMode=parse_blend_mode(self.blend_mode)
        )
        if self.should_save:
            canvas.saveLayer(None, paint)
        for cmd in self.children:
            cmd.execute(canvas)
        if self.should_save:
            canvas.restore()

    def map(self, rect):
        if (
            self.children
            and isinstance(self.children[-1], Blend)
            and self.children[-1].blend_mode == "destination-in"
        ):
            bounds = rect.makeOffset(0.0, 0.0)
            bounds.intersect(self.children[-1].rect)
            return bounds
        else:
            return rect

    def unmap(self, rect):
        return rect

    def clone(self, child):
        return Blend(self.opacity, self.blend_mode, self.node, [child])

    def __repr__(self):
        args = ""
        if self.opacity < 1:
            args += ", opacity={}".format(self.opacity)
        if self.blend_mode:
            args += ", blend_mode={}".format(self.blend_mode)
        if not args:
            args = ", <no-op>"
        return "Blend({})".format(args[2:])


def paint_visual_effects(node, cmds, rect):
    opacity = float(node.style.get("opacity", "1.0"))
    blend_mode = node.style.get("mix-blend-mode")
    translation = parse_transform(node.style.get("transform", ""))

    if node.style.get("overflow", "visible") == "clip":
        if not blend_mode:
            blend_mode = "source-over"

    if node.style.get("overflow", "visible") == "clip":
        border_radius = float(node.style.get("border-radius", "0px")[0:-2])
        cmds.append(
            Blend(
                1.0, "destination-in", None, [DrawRRect(rect, border_radius, "black")]
            )
        )

    blend_op = Blend(opacity, blend_mode, node, cmds)
    node.blend_op = blend_op
    return [Transform(translation, rect, node, [blend_op])]


class Transform(VisualEffect):
    def __init__(self, translation, rect, node, children):
        super().__init__(rect, children, node)
        self.self_rect = rect
        self.translation = translation

    def execute(self, canvas):
        if self.translation:
            x, y = self.translation
            canvas.save()
            canvas.translate(x, y)
        for cmd in self.children:
            cmd.execute(canvas)
        if self.translation:
            canvas.restore()

    def map(self, rect):
        return map_translation(rect, self.translation)

    def unmap(self, rect):
        return map_translation(rect, self.translation, True)

    def clone(self, child):
        return Transform(self.translation, self.self_rect, self.node, [child])

    def __repr__(self):
        if self.translation:
            x, y = self.translation
            return "Transform(translate({}, {}))".format(x, y)
        else:
            return "Transform(<no-op>)"
