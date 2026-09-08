import skia
from html_parser import Element
from constants import *
from html_parser import Text
from utils import *
from constants import *


def parse_transition(value):
    properties = {}
    if not value:
        return properties
    for item in value.split(","):
        property, duration = item.split(" ", 1)
        frames = int(float(duration[:-1]) / REFRESH_RATE_SEC)
        properties[property] = frames
    return properties


def diff_styles(old_style, new_style):
    transitions = {}
    for property, num_frames in parse_transition(new_style.get("transition")).items():
        if property not in old_style:
            continue
        if property not in new_style:
            continue
        old_value = old_style[property]
        new_value = new_style[property]
        if old_value == new_value:
            continue
        transitions[property] = (old_value, new_value, num_frames)

    return transitions


class CSSParser:
    def __init__(self, s):
        self.s = s
        self.i = 0

    def whitespace(self):
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def word(self):
        start = self.i
        while self.i < len(self.s):
            if self.s[self.i].isalnum() or self.s[self.i] in "#-.%":
                self.i += 1
            else:
                break
        if not (self.i > start):
            raise Exception("Parsing error")
        return self.s[start : self.i]

    def literal(self, literal):
        if not (self.i < len(self.s) and self.s[self.i] == literal):
            raise Exception("Parsing error")
        self.i += 1

    def until_chars(self, chars):
        start = self.i
        while self.i < len(self.s) and self.s[self.i] not in chars:
            self.i += 1
        return self.s[start : self.i]

    def pair(self, until):
        prop = self.word()
        self.whitespace()
        self.literal(":")
        self.whitespace()
        value = self.until_chars(until)
        return prop.casefold(), value.strip()

    def body(self):
        pairs = {}
        while self.i < len(self.s) and self.s[self.i] != "}":
            try:
                prop, value = self.pair([";", "}"])
                pairs[prop.casefold()] = value
                self.whitespace()
                self.literal(";")
                self.whitespace()
            except Exception:
                why = self.ignore_until([";", "}"])
                if why == ";":
                    self.literal(";")
                    self.whitespace()
                else:
                    break
        return pairs

    def ignore_until(self, chars):
        while self.i < len(self.s):
            if self.s[self.i] in chars:
                return self.s[self.i]
            else:
                self.i += 1
        return None

    def simple_selector(self):
        out = TagSelector(self.word().casefold())
        if self.i < len(self.s) and self.s[self.i] == ":":
            self.literal(":")
            pseudoclass = self.word().casefold()
            out = PseudoClassSelector(pseudoclass, out)
        return out

    def selector(self):
        out = self.simple_selector()
        self.whitespace()
        while self.i < len(self.s) and self.s[self.i] != "{":
            descendant = self.simple_selector()
            out = DescendantSelector(out, descendant)
            self.whitespace()
        return out

    def media_query(self):
        self.literal("@")
        assert self.word() == "media"
        self.whitespace()
        self.literal("(")
        self.whitespace()
        prop, val = self.pair([")"])
        self.whitespace()
        self.literal(")")
        return prop, val

    def parse(self):
        rules = []
        media = None
        self.whitespace()
        while self.i < len(self.s):
            try:
                if self.s[self.i] == "@" and not media:
                    prop, val = self.media_query()
                    if prop == "prefers-color-scheme" and val in ["dark", "light"]:
                        media = val
                    self.whitespace()
                    self.literal("{")
                    self.whitespace()
                elif self.s[self.i] == "}" and media:
                    self.literal("}")
                    media = None
                    self.whitespace()
                else:
                    selector = self.selector()
                    self.literal("{")
                    self.whitespace()
                    body = self.body()
                    self.literal("}")
                    self.whitespace()
                    rules.append((media, selector, body))
            except Exception:
                why = self.ignore_until(["}"])
                if why == "}":
                    self.literal("}")
                    self.whitespace()
                else:
                    break
        return rules


class TagSelector:
    def __init__(self, tag):
        self.tag = tag
        self.priority = 1

    def matches(self, node):
        return isinstance(node, Element) and node.tag == self.tag


class DescendantSelector:
    def __init__(self, ancestor, descendant):
        self.ancestor = ancestor
        self.descendant = descendant
        self.priority = ancestor.priority + descendant.priority

    def matches(self, node):
        if not self.descendant.matches(node):
            return False
        while node.parent:
            if self.ancestor.matches(node.parent):
                return True
            node = node.parent
        return False


class PseudoClassSelector:
    def __init__(self, pseudoclass, base):
        self.pseudoclass = pseudoclass
        self.base = base
        self.priority = self.base.priority

    def matches(self, node):
        if not self.base.matches(node):
            return False
        if self.pseudoclass == "focus":
            return node.is_focused
        else:
            return False


def style(node, rules, tab):
    old_style = node.style
    node.style = {}

    for property, default_value in INHERITED_PROPERTIES.items():
        if node.parent:
            node.style[property] = node.parent.style[property]
        else:
            node.style[property] = default_value

    for media, selector, body in rules:
        if media:
            if (media == "dark") != tab.dark_mode:
                continue
        if not selector.matches(node):
            continue
        for property, value in body.items():
            node.style[property] = value

    if isinstance(node, Element) and "style" in node.attributes:
        pairs = CSSParser(node.attributes["style"]).body()
        for prop, value in pairs.items():
            node.style[prop] = value

    if node.style["font-size"].endswith("%"):
        # print("node: ", node, node.style)
        if node.parent:
            parent_font_size = node.parent.style["font-size"]
        else:
            parent_font_size = INHERITED_PROPERTIES["font-size"]
        node_pct = float(node.style["font-size"][:-1]) / 100
        parent_px = float(parent_font_size[:-2])
        node.style["font-size"] = str(node_pct * parent_px) + "px"

    for child in node.children:
        style(child, rules, tab)

    if old_style:
        transitions = diff_styles(old_style, node.style)
        for property, (old_value, new_value, num_frames) in transitions.items():
            if property == "opacity":
                tab.set_needs_render()
                animation = NumericAnimation(old_value, new_value, num_frames)
                node.animations[property] = animation
                node.style[property] = animation.animate()


def cascade_priority(rule):
    media, selector, body = rule
    return selector.priority


def map_translation(rect, translation, reversed=False):
    if not translation:
        return rect
    else:
        x, y = translation
        matrix = skia.Matrix()
        if reversed:
            matrix.setTranslate(-x, -y)
        else:
            matrix.setTranslate(x, y)
        return matrix.mapRect(rect)


def absolute_bounds_for_obj(obj):
    rect = skia.Rect.MakeXYWH(obj.x, obj.y, obj.width, obj.height)
    cur = obj.node
    while cur:
        rect = map_translation(rect, parse_transform(cur.style.get("transform", "")))
        cur = cur.parent
    return rect


def parse_outline(outline_str):
    if not outline_str:
        return None
    values = outline_str.split(" ")
    if len(values) != 3:
        return None
    if values[1] != "solid":
        return None
    return int(values[0][:-2]), values[2]


def paint_outline(node, cmds, rect, zoom):
    outline = parse_outline(node.style.get("outline"))
    if not outline:
        return
    thickness, color = outline
    cmds.append(DrawOutline(rect, color, dpx(thickness, zoom)))


class NumericAnimation:
    def __init__(self, old_value, new_value, num_frames):
        self.old_value = float(old_value)
        self.new_value = float(new_value)
        self.num_frames = num_frames

        self.frame_count = 1
        total_change = self.new_value - self.old_value
        self.change_per_frame = total_change / num_frames

    def animate(self):
        self.frame_count += 1
        if self.frame_count >= self.num_frames:
            return
        current_value = self.old_value + self.change_per_frame * self.frame_count
        return str(current_value)


class PaintCommand:
    def __init__(self, rect):
        self.rect = rect
        self.children = []


class DrawCompositedLayer(PaintCommand):
    def __init__(self, composited_layer):
        self.composited_layer = composited_layer
        super().__init__(composited_layer.composited_bounds())

    def execute(self, canvas):
        layer = self.composited_layer
        if not layer.surface:
            return
        bounds = layer.composited_bounds()
        layer.surface.draw(canvas, bounds.left(), bounds.top())

    def __repr__(self):
        return "DrawCompositedLayer()"


class CompositedLayer:
    def __init__(self, skia_context, display_item):
        self.skia_context = skia_context
        self.surface = None
        self.display_items = [display_item]

    def composited_bounds(self):
        rect = skia.Rect.MakeEmpty()
        for item in self.display_items:
            rect.join(absolute_to_local(item, local_to_absolute(item, item.rect)))
        rect.outset(1, 1)
        return rect

    def raster(self):
        bounds = self.composited_bounds()
        if bounds.isEmpty():
            return
        irect = bounds.roundOut()

        if not self.surface:
            self.surface = skia.Surface.MakeRenderTarget(
                self.skia_context,
                skia.Budgeted.kNo,
                skia.ImageInfo.MakeN32Premul(irect.width(), irect.height()),
            )
            if not self.surface:
                self.surface = skia.Surface(irect.width(), irect.height())
            assert self.surface

        canvas = self.surface.getCanvas()

        canvas.clear(skia.ColorTRANSPARENT)
        canvas.save()
        canvas.translate(-bounds.left(), -bounds.top())
        for item in self.display_items:
            item.execute(canvas)
        canvas.restore()

        if SHOW_COMPOSITED_LAYER_BORDERS:
            border_rect = skia.Rect.MakeXYWH(
                1, 1, irect.width() - 2, irect.height() - 2
            )
            DrawOutline(border_rect, "red", 1).execute(canvas)

    def add(self, display_item):
        self.display_items.append(display_item)

    def can_marge(self, display_item):
        return display_item.parent == self.display_items[0].parent

    def absolute_bounds(self):
        rect = skia.Rect.MakeEmpty()
        for item in self.display_items:
            rect.join(local_to_absolute(item, item.rect))
        return rect


def parse_image_rendering(quality):
    if quality == "high-quality":
        return skia.FilterQuality.kHigh_FilterQuality
    elif quality == "crisp-edges":
        return skia.FilterQuality.kLow_FilterQuality
    else:
        return skia.FilterQuality.kMedium_FilterQuality


class DrawImage(PaintCommand):
    def __init__(self, image, rect, quality):
        super().__init__(rect)
        self.image = image
        self.quality = parse_image_rendering(quality)

    def execute(self, canvas):
        paint = skia.Paint(FilterQuality=self.quality)
        canvas.drawImageRect(self.image, self.rect, paint)


class DocumentLayout:
    def __init__(self, node):
        self.node = node
        self.parent = None
        self.children = []
        self.zoom = 1

    def paint(self):
        return []

    def layout(self, zoom):
        self.zoom = zoom
        self.width = WIDTH - 2 * dpx(HSTEP, self.zoom)
        self.x = dpx(HSTEP, self.zoom)
        self.y = dpx(VSTEP, self.zoom)

        child = BlockLayout(self.node, self, None)
        self.children.append(child)
        child.layout()

        self.height = child.height

    def should_paint(self):
        return True

    def paint_effects(self, cmds):
        return cmds


class DrawText(PaintCommand):
    def __init__(self, x1, y1, text, font, color):
        self.top = y1
        self.left = x1
        self.text = text
        self.font = font
        self.right = x1 + font.measureText(text)
        self.color = color
        self.bottom = y1 + linespace(font)
        super().__init__(skia.Rect.MakeLTRB(x1, y1, self.right, self.bottom))

        self.rect = skia.Rect.MakeLTRB(x1, y1, self.right, self.bottom)

    def execute(self, canvas):
        paint = skia.Paint(AntiAlias=True, Color=parse_color(self.color))
        baseline = self.rect.top() - self.font.getMetrics().fAscent
        canvas.drawString(
            self.text, float(self.rect.left()), baseline, self.font, paint
        )


class DrawRRect(PaintCommand):
    def __init__(self, rect, radius, color):
        super().__init__(rect)
        self.rect = rect  # FIX: store rect so tab.draw can call cmd.rect.top()
        self.rrect = skia.RRect.MakeRectXY(rect, radius, radius)
        self.color = color

    def execute(self, canvas):
        paint = skia.Paint(
            Color=parse_color(self.color),
        )
        canvas.drawRRect(self.rrect, paint)

    def __repr__(self):
        return ("DrawRect(rrect={} color={})").format(str(self.rrect), self.color)


class DrawRect(PaintCommand):
    def __init__(self, rect, radius, color):
        self.rect = rect  # FIX: store rect so tab.draw can call cmd.rect.top()
        super().__init__(rect)
        self.rrect = skia.RRect.MakeRectXY(rect, radius, radius)
        self.color = color

    def execute(self, canvas):
        paint = skia.Paint(
            Color=parse_color(self.color),
        )
        canvas.drawRect(self.rect, paint)

    def __repr__(self):
        return ("DrawRect(rect={} color={})").format(str(self.rect), self.color)


class DrawOutline(PaintCommand):
    def __init__(self, rect, color, thickness):
        super().__init__(rect)
        self.rect = rect
        self.color = color
        self.thickness = thickness

    def execute(self, canvas):
        paint = skia.Paint(
            Color=parse_color(self.color),
            StrokeWidth=self.thickness,
            Style=skia.Paint.kStroke_Style,
        )
        canvas.drawRect(self.rect, paint)


class DrawLine(PaintCommand):
    def __init__(self, x1, y1, x2, y2, color, thickness):
        super().__init__(skia.Rect.MakeLTRB(x1, y1, x2, y2))
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.rect = skia.Rect.MakeLTRB(x1, y1, x2, y2)
        self.color = color
        self.thickness = thickness

    def execute(self, canvas):
        path = (
            skia.Path()
            .moveTo(self.rect.left(), self.rect.top())
            .lineTo(self.rect.right(), self.rect.bottom())
        )
        paint = skia.Paint(
            Color=parse_color(self.color),
            StrokeWidth=self.thickness,
            Style=skia.Paint.kStroke_Style,
        )
        canvas.drawPath(path, paint)


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


class EmbedLayout:
    def __init__(self, node, parent, previous, frame):
        self.node = node
        self.frame = frame
        self.layout_object = self
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


class TextLayout:
    def __init__(self, node, word, parent, previous):
        self.node = node
        self.word = word
        self.children = []
        self.parent = parent
        self.previous = previous

        self.font = None
        self.weight = 0
        self.style = "roman"
        self.size = 0
        self.height = 0
        self.x = 0
        self.y = 0

    def layout(self):
        self.zoom = self.parent.zoom
        self.font = font(self.node.style, self.zoom)

        self.width = self.font.measureText(self.word)

        if self.previous:
            space = self.previous.font.measureText(" ")
            self.x = self.previous.x + space + self.previous.width
        else:
            self.x = self.parent.x

        self.height = linespace(self.font)

        self.ascent = self.font.getMetrics().fAscent * 1.25
        self.descent = self.font.getMetrics().fDescent * 1.25

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


class InputLayout(EmbedLayout):
    def __init__(self, node, parent, previous):
        super().__init__(node, parent, previous, None)

    def layout(self):
        super().layout()

        self.width = dpx(INPUT_WIDTH_PX, self.zoom)
        self.height = linespace(self.font)

        self.ascent = -self.height
        self.descent = 0

    def paint(self):
        cmds = []

        bgcolor = self.node.style.get("background-color", "transparent")
        if bgcolor != "transparent":
            radius = dpx(
                float(self.node.style.get("border-radius", "0px")[:-2]), self.zoom
            )
            rect = DrawRRect(self.self_rect(), radius, bgcolor)
            cmds.append(rect)

        if self.node.tag == "input":
            text = self.node.attributes.get("value", "")
        elif self.node.tag == "button":
            if len(self.node.children) == 1 and isinstance(self.node.children[0], Text):
                text = self.node.children[0].text
            else:
                print("Ignoring HTML contents inside button")
                text = ""

        color = self.node.style["color"]
        cmds.append(DrawText(self.x, self.y, text, self.font, color))

        if self.node.is_focused and self.node.tag == "input":
            cx = self.x + self.font.measureText(text)
            cmds.append(DrawLine(cx, self.y, cx, self.y + self.height, color, 1))

        return cmds

    def self_rect(self):
        return skia.Rect.MakeLTRB(
            self.x, self.y, self.x + self.width, self.y + self.height
        )

    def should_paint(self):
        return True

    def paint_effects(self, cmds):
        cmds = paint_visual_effects(self.node, cmds, self.self_rect())
        paint_outline(self.node, cmds, self.self_rect(), self.zoom)
        return cmds


class ImageLayout(EmbedLayout):
    def __init__(self, node, parent, previous, frame):
        super().__init__(node, parent, previous, frame)

    def layout(self):
        super().layout()

        width_attr = self.node.attributes.get("width")
        height_attr = self.node.attributes.get("height")
        image_width = self.node.image.width()
        image_height = self.node.image.height()
        aspect_ratio = image_width / image_height

        if width_attr and height_attr:
            self.width = dpx(int(width_attr), self.zoom)
            self.img_height = dpx(int(height_attr), self.zoom)
        elif width_attr:
            self.width = dpx(int(width_attr), self.zoom)
            self.img_height = self.width / aspect_ratio
        elif height_attr:
            self.img_height = dpx(int(height_attr), self.zoom)
            self.width = self.img_height * aspect_ratio
        else:
            self.width = dpx(image_width, self.zoom)
            self.img_height = dpx(image_height, self.zoom)

        self.height = max(self.img_height, linespace(self.font))

        self.ascent = -self.height
        self.descent = 0

    def paint(self):
        cmds = []
        rect = skia.Rect.MakeLTRB(
            self.x,
            self.y + self.height - self.img_height,
            self.x + self.width,
            self.y + self.height,
        )
        quality = self.node.style.get("image-rendering", "auto")
        cmds.append(DrawImage(self.node.image, rect, quality))
        return cmds

    def paint_effects(self, cmds):
        return cmds


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
                internal_cmds,
            )
        )
        cmds = [Blend(1.0, "source-over", self.node, internal_cmds)]
        paint_outline(self.node, cmds, rect, self.zoom)
        cmds = paint_visual_effects(self.node, cmds, rect)

        return cmds


class LineLayout(EmbedLayout):
    def __init__(self, node, parent, previous):
        self.node = node
        self.parent = parent
        self.previous = previous
        self.children = []

        self.x = None
        self.y = None
        self.width = 0
        self.height = 0

    def layout(self):
        self.zoom = self.parent.zoom
        self.width = self.parent.width
        self.x = self.parent.x

        if self.previous:
            self.y = self.previous.y + self.previous.height
        else:
            self.y = self.parent.y

        for word in self.children:
            word.layout()

        if not self.children:
            self.height = 0
            return

        max_ascent = max([-child.ascent for child in self.children])
        baseline = self.y + max_ascent

        for child in self.children:
            if isinstance(child, TextLayout):
                child.y = baseline + child.ascent / 1.25
            else:
                child.y = baseline + child.ascent

        max_descent = max([child.descent for child in self.children])
        self.height = max_ascent + max_descent

    def paint(self):
        return []

    def should_paint(self):
        return True

    def paint_effects(self, cmds):
        outline_rect = skia.Rect.MakeEmpty()
        outline_node = None
        for child in self.children:
            outline_str = child.node.parent.style.get("outline")
            if parse_outline(outline_str):
                outline_rect.join(child.self_rect())
                outline_node = child.node.parent
        if outline_node:
            paint_outline(outline_node, cmds, outline_rect, self.zoom)
        return cmds


class Opacity:
    def __init__(self, opacity, children):
        self.opacity = opacity
        self.children = children
        self.rect = skia.Rect.MakeEmpty()
        for cmd in self.children:
            self.rect.join(cmd.rect)

    def execute(self, canvas):
        paint = skia.Paint(
            Alphaf=self.opacity,
        )
        if self.opacity < 1:
            canvas.saveLayer(None, paint)
        for cmd in self.children:
            cmd.execute(canvas)
        if self.opacity < 1:
            canvas.restore()


def parse_blend_mode(blend_mode_str):
    if blend_mode_str == "multiply":
        return skia.BlendMode.kMultiply
    elif blend_mode_str == "difference":
        return skia.BlendMode.kDifference
    elif blend_mode_str == "destination-in":
        return skia.BlendMode.kDstIn
    elif blend_mode_str == "source-over":
        return skia.BlendMode.kSrcOver
    else:
        return skia.BlendMode.kSrcOver


def local_to_absolute(display_item, rect):
    while display_item.parent:
        rect = display_item.parent.map(rect)
        display_item = display_item.parent
    return rect


def absolute_to_local(display_item, rect):
    parent_chain = []
    while display_item.parent:
        parent_chain.append(display_item.parent)
        display_item = display_item.parent
    for parent in reversed(parent_chain):
        rect = parent.unmap(rect)
    return rect


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


def parse_transform(transform_str):
    if transform_str.find("translate(") < 0:
        return None
    left_paren = transform_str.find("(")
    right_paren = transform_str.find(")")
    x_px, y_px = transform_str[left_paren + 1 : right_paren].split(",")
    return (float(x_px.strip()[:-2]), float(y_px.strip()[:-2]))


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


class BlockLayout:
    def __init__(self, node, parent, previous, frame):
        self.node = node
        node.layout_object = self
        self.parent = parent
        self.previous = previous
        self.children = []

        self.x = None
        self.y = None
        self.width = None
        self.height = None

        self.frame = frame

        # self.display_list = []
        # self.weight = "normal"
        # self.style = "roman"
        # self.cursor_x, self.cursor_y = HSTEP, VSTEP
        # self.size = 12
        # self.word_font = get_font(self.size, self.weight, self.style)

        # for child in self.children:
        #     child.layout()

    def self_rect(self):
        return skia.Rect.MakeXYWH(
            self.x, self.y, self.x + self.width, self.y + self.height
        )

    def paint(self):
        cmds = []

        bgcolor = self.node.style.get("background-color", "transparent")

        if bgcolor != "transparent":
            radius = float(self.node.style.get("border-radius", "0px")[:-2])
            rect = DrawRRect(self.self_rect(), radius, bgcolor)
            cmds.append(rect)

        if self.layout_mode() == "inline":
            for x, y, word, font, color in self.display_list:
                cmds.append(DrawText(x, y, word, font, color))

        return cmds

    def input(self, node):
        w = dpx(INPUT_WIDTH_PX, self.zoom)
        self.add_inline_child(node, w, InputLayout, self.frame)

    def layout(self):
        self.zoom = self.parent.zoom
        self.x = self.parent.x
        self.width = self.parent.width

        if self.previous:
            self.y = self.previous.y + self.previous.height
        else:
            self.y = self.parent.y

        mode = self.layout_mode()
        if mode == "block":
            previous = None
            for child in self.node.children:
                next = BlockLayout(child, self, previous)
                self.children.append(next)
                previous = next
        else:
            self.new_line()
            self.recurse(self.node)

        for child in self.children:
            child.layout()

        self.height = sum([child.height for child in self.children])

    def recurse(self, node):
        if isinstance(node, Text):
            for word in node.text.split():
                self.word(node, word)
        else:
            if node.tag == "br":
                self.new_line()
            elif node.tag == "input" or node.tag == "button":
                self.input(node)
            elif node.tag == "img":
                self.image(node)
            elif node.tag == "iframe" and "src" in node.attributes:
                self.iframe(node)
            else:
                for child in node.children:
                    self.recurse(child)

    def open_tag(self, tag):
        if tag == "i":
            self.style = "italic"
        elif tag == "b":
            self.weight = "bold"
        elif tag == "br":
            self.flush()
            self.cursor_x = HSTEP
            self.cursor_y += linespace(self.word_font) * 1.25
        elif tag == "p" or tag == "div":
            self.flush()
            self.cursor_y += VSTEP
        elif tag == "pre":
            self.style = "roman"
            self.cursor_x = HSTEP
            self.cursor_y += linespace(self.word_font) * 1.25
        elif tag == "small":
            self.size -= 2
        elif tag == "big":
            self.size += 4

    def close_tag(self, tag):
        if tag == "i":
            self.style = "roman"
        elif tag == "b":
            self.weight = "normal"
        elif tag == "small":
            self.size += 2
        elif tag == "big":
            self.size -= 4

    def new_line(self):
        self.cursor_x = self.x
        last_line = self.children[-1] if self.children else None
        new_line = LineLayout(self.node, self, last_line)
        self.children.append(new_line)

    def word(self, node, word):
        node_font = font(node.style, self.zoom)
        w = node_font.measureText(word)
        self.add_inline_child(node, w, TextLayout, word)

    def image(self, node):
        if "width" in node.attributes:
            w = dpx(int(node.attributes["width"]), self.zoom)
        else:
            w = dpx(node.image.width(), self.zoom)
        self.add_inline_child(node, w, ImageLayout)

    def iframe(self, node):
        if "width" in self.node.attributes:
            w = dpx(int(self.node.attributes["width"]), self.zoom)
        else:
            w = IFRAME_WIDTH_PX + dpx(2, self.zoom)
        self.add_inline_child(node, w, IframeLayout, self.frame)

    def flush(self):
        if not self.line:
            return
        max_ascent = max([f.getMetrics().fAscent for x, word, f, color in self.line])
        baseline = self.cursor_y * 1.25 + max_ascent

        for rel_x, word, f, color in self.line:
            x = self.x + rel_x
            y = self.y + baseline - f.getMetrics().fAscent
            self.display_list.append((x, y, word, f, color))

        max_descent = max(f.getMetrics().fAscent for _, _, f, _ in self.line)
        self.cursor_y = baseline + max_descent * 1.25
        self.cursor_x = HSTEP
        self.line = []

    def layout_intermediate(self):
        previous = None
        for child in self.node.children:
            next = BlockLayout(child, self, previous)
            self.children.append(next)
            previous = next

    def layout_mode(self):
        if isinstance(self.node, Text):
            return "inline"
        elif self.node.children:
            for child in self.node.children:
                if isinstance(child, Text):
                    continue
                if child.tag in BLOCK_ELEMENTS:
                    return "block"
            return "inline"
        elif self.node.tag in ["input", "img", "iframe"]:
            return "inline"
        else:
            return "block"

    def should_paint(self):
        return isinstance(self.node, Text) or (
            self.node.tag not in ["input", "button", "img"]
        )

    def paint_effects(self, cmds):
        cmds = paint_visual_effects(self.node, cmds, self.self_rect())

        return cmds

    def add_inline_child(self, node, w, child_class, frame, word=None):
        if self.cursor_x + w > self.x + self.width:
            self.new_line()
        line = self.children[-1]
        previous_word = line.children[-1] if line.children else None
        if word:
            child = child_class(node, word, line, previous_word)
        else:
            child = child_class(node, line, previous_word, frame)
        line.children.append(child)
        self.cursor_x += w + font(node.style, self.zoom).measureText(" ")
