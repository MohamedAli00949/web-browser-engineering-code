import skia
from html_parser import *
from constants import *
from html_parser import Text
from utils import *
from constants import *
from iframe_layout import *
from embed_layout import *
from line_layout import *
from transform_effects import *
from composite_layer import *
from paint_command import *
from protected_field import *


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


def init_style(node):
    node.style = dict(
        [
            (
                property,
                ProtectedField(
                    node,
                    property,
                    None,
                    (
                        [node.parent.style[property]]
                        if node.parent and property in INHERITED_PROPERTIES
                        else []
                    ),
                ),
            )
            for property in CSS_PROPERTIES
        ]
    )


def style(node, rules, frame):
    if not node.style:
        init_style(node)
    needs_style = any([field.dirty for field in node.style.values()])
    if needs_style:
        old_style = dict(
            [(property, field.value) for property, field in node.style.items()]
        )
        new_style = CSS_PROPERTIES.copy()

        for property, default_value in INHERITED_PROPERTIES.items():
            if node.parent:
                # parent_style = node.parent.style.read(notify=node.style)
                parent_field = node.parent.style[property]
                parent_value = parent_field.read(notify=node.style[property])
                new_style[property] = parent_value
            else:
                new_style[property] = default_value

        for media, selector, body in rules:
            if media:
                if (media == "dark") != frame.tab.dark_mode:
                    continue
            if not selector.matches(node):
                continue
            for property, value in body.items():
                new_style[property] = value

        if isinstance(node, Element) and "style" in node.attributes:
            pairs = CSSParser(node.attributes["style"]).body()
            for prop, value in pairs.items():
                new_style[prop] = value

        if new_style["font-size"].endswith("%"):
            # print("node: ", node, node.style)
            if node.parent:
                parent_field = node.parent.style["font-size"]
                parent_font_size = parent_field.read(notify=node.style["font-size"])
            else:
                parent_font_size = INHERITED_PROPERTIES["font-size"]
            node_pct = float(new_style["font-size"][:-1]) / 100
            parent_px = float(parent_font_size[:-2])
            new_style["font-size"] = str(node_pct * parent_px) + "px"

        if old_style:
            transitions = diff_styles(old_style, new_style)
            for property, (old_value, new_value, num_frames) in transitions.items():
                if property == "opacity":
                    frame.set_needs_render()
                    animation = NumericAnimation(old_value, new_value, num_frames)
                    node.animations[property] = animation
                    new_style[property] = animation.animate()

        for property, field in node.style.items():
            field.set(new_style[property])

    for child in node.children:
        style(child, rules, frame)


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
    def __init__(self, node, frame):
        self.node = node
        self.frame = frame
        self.layout_object = self
        self.parent = None
        self.previous = None
        self.children = []
        self.zoom = ProtectedField(self, "zoom", None, [])
        self.width = ProtectedField(self, "width", None, [])
        self.x = ProtectedField(self, "x", None, [])
        self.y = ProtectedField(self, "y", None, [])
        self.height = ProtectedField(self, "height")

        self.has_dirty_descendants = True

    def paint(self):  # done
        return []

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
        if self.has_dirty_descendants:
            return True
        return False

    def layout(self, width, zoom):  # done
        if not self.layout_needed():
            return
        # self.zoom.mark()
        # zoom = self.zoom.read(notify=child)
        self.zoom.set(zoom)
        self.width.set(width - 2 * dpx(HSTEP, zoom))

        if not self.children:
            child = BlockLayout(self.node, self, None, self.frame)
            self.height.set_dependencies([child.height])
        else:
            child = self.children[0]
        self.children = [child]

        self.x.set(dpx(HSTEP, zoom))
        self.y.set(dpx(VSTEP, zoom))

        child.layout()
        self.has_dirty_descendants = False

        self.height.copy(child.height)

    def should_paint(self):
        return True

    def paint_effects(self, cmds):  # done
        if self.frame != self.frame.tab.root_frame and self.frame.scroll != 0:
            rect = skia.Rect.MakeXYWH(
                self.x.get(),
                self.y.get(),
                self.x.get() + self.width.get(),
                self.y.get() + self.height.get(),
            )
            cmds = [Transform((0, -self.frame.scroll), rect, self.node, cmds)]
        return cmds


class InputLayout(EmbedLayout):
    def __init__(self, node, parent, previous, frame):
        super().__init__(node, parent, previous, frame)

    def layout(self):  # done
        if not self.layout_needed():
            return
        super().layout()
        zoom = self.zoom.read(notify=self.width)
        self.width.set(dpx(INPUT_WIDTH_PX, zoom))

        font = self.font.read(notify=self.height)
        self.height.set(linespace(font))

        height = self.height.read(notify=self.ascent)
        self.ascent.set(-height)
        self.descent.set(0)

    def paint(self):  # done
        cmds = []

        # bgcolor = self.node.style.get("background-color", "transparent")
        bgcolor = self.node.style["background-color"].get()
        if bgcolor != "transparent":
            # radius = dpx(
            #     float(self.node.style.get("border-radius", "0px")[:-2]), self.zoom.get()
            # )
            radius = dpx(
                float(self.node.style["border-radius"].get()[:-2]), self.zoom.get()
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

        # color = self.node.style["color"]
        color = self.node.style["color"].get()
        cmds.append(DrawText(self.x.get(), self.y.get(), text, self.font.get(), color))

        if self.node.is_focused and self.node.tag == "input":
            cx = self.x.get() + self.font.get().measureText(text)
            cmds.append(DrawCursor(self, self.font.get().measureText(text)))

        return cmds

    def self_rect(self):  # done
        return skia.Rect.MakeLTRB(
            self.x.get(),
            self.y.get(),
            self.x.get() + self.width.get(),
            self.y.get() + self.height.get(),
        )

    def should_paint(self):
        return True

    def paint_effects(self, cmds):  # done
        cmds = paint_visual_effects(self.node, cmds, self.self_rect())
        paint_outline(self.node, cmds, self.self_rect(), self.zoom.get())
        return cmds


class ImageLayout(EmbedLayout):
    def __init__(self, node, parent, previous, frame):
        super().__init__(node, parent, previous, frame)

    def layout(self):  # done
        if not self.layout_needed():
            return
        super().layout()

        width_attr = self.node.attributes.get("width")
        height_attr = self.node.attributes.get("height")
        image_width = self.node.image.width()
        image_height = self.node.image.height()
        aspect_ratio = image_width / image_height

        w_zoom = self.zoom.read(notify=self.width)
        h_zoom = self.zoom.read(notify=self.height)
        if width_attr and height_attr:
            self.width.set(dpx(int(width_attr), w_zoom))
            self.img_height = dpx(int(height_attr), h_zoom)
        elif width_attr:
            self.width.set(dpx(int(width_attr), w_zoom))
            w = self.width.read(notify=self.height)
            self.img_height = w / aspect_ratio
        elif height_attr:
            self.img_height = dpx(int(height_attr), h_zoom)
            self.width.set(self.img_height * aspect_ratio)
        else:
            self.width.set(dpx(image_width, w_zoom))
            self.img_height = dpx(image_height, h_zoom)

        font = self.font.read(notify=self.height)
        self.height.set(max(self.img_height, linespace(font)))

        height = self.height.read(notify=self.ascent)
        self.ascent.set(-height)
        self.descent.set(0)

    def paint(self):  # done
        cmds = []
        rect = skia.Rect.MakeLTRB(
            self.x.get(),
            self.y.get() + self.height.get() - self.img_height,
            self.x.get() + self.width.get(),
            self.y.get() + self.height.get(),
        )
        quality = self.node.style["image-rendering"].get()
        cmds.append(DrawImage(self.node.image, rect, quality))
        return cmds

    def paint_effects(self, cmds):
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


def DrawCursor(elt, offset): # done
    x = elt.x.get() + offset
    return DrawLine(x, elt.y.get(), x, elt.y.get() + elt.height.get(), "red", 1)

class BlockLayout:
    def __init__(self, node, parent, previous, frame):
        self.node = node
        node.layout_object = self
        self.parent = parent
        self.previous = previous
        self.frame = frame

        self.zoom = ProtectedField(self, "zoom", self.parent, [self.parent.zoom])
        self.width = ProtectedField(self, "width", self.parent, [self.parent.width])
        self.height = ProtectedField(self, "height", self.parent)
        self.x = ProtectedField(self, "x", self.parent, [self.parent.x])

        if self.previous:
            y_dependencies = [self.previous.y, self.previous.height]
        else:
            y_dependencies = [self.parent.y]
        self.y = ProtectedField(self, "y", self.parent, y_dependencies)

        self.children = ProtectedField(self, "children", self.parent, None, [])

        self.has_dirty_descendants = True

    def self_rect(self):
        return skia.Rect.MakeLTRB(
            self.x.get(),
            self.y.get(),
            self.x.get() + self.width.get(),
            self.y.get() + self.height.get(),
        )

    def paint(self):
        assert not self.children.dirty
        cmds = []

        bgcolor = self.node.style["background-color"].get()

        if bgcolor != "transparent":
            radius = dpx(
                float(self.node.style["border-radius"].get()[:-2]), self.zoom.get()
            )
            rect = DrawRRect(self.self_rect(), radius, bgcolor)
            cmds.append(rect)

        # if self.node.is_focused and "contenteditable" in self.node.attributes:
        #     text_nodes = [
        #         t for t in tree_to_list(self.node, []) if isinstance(t, TextLayout)
        #     ]
        #     if text_nodes:
        #         cmds.append(DrawCursor(text_nodes[-1], text_nodes[-1].width))
        #     else:
        #         cmds.append(DrawCursor(self, 0))
        # # if self.layout_mode() == "inline":
        # #     for x, y, word, font, color in self.display_list:
        # #         cmds.append(DrawText(x, y, word, font, color))

        return cmds

    def input(self, node):
        zoom = self.zoom.read(notify=self.children)
        w = dpx(INPUT_WIDTH_PX, zoom)
        self.add_inline_child(node, w, InputLayout, self.frame)

    def layout_needed(self):
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
        if self.children.dirty:
            return True
        if self.has_dirty_descendants:
            return True
        return False

    def layout(self):
        if not self.layout_needed():
            return

        self.zoom.copy(self.parent.zoom)
        self.x.copy(self.parent.x)
        self.width.copy(self.parent.width)

        if self.previous:
            prev_y = self.previous.y.read(notify=self.y)
            prev_height = self.previous.height.read(notify=self.y)
            self.y.set(prev_y + prev_height)
        else:
            self.y.copy(self.parent.y)

        mode = self.layout_mode()
        if mode == "block":
            if self.children.dirty:
                children = []
                previous = None
                for child in self.node.children:
                    next = BlockLayout(child, self, previous, self.frame)
                    children.append(next)
                    previous = next
                self.children.set(children)

                height_dependencies = [child.height for child in children]
                height_dependencies.append(self.children)
                self.height.set_dependencies(height_dependencies)
        else:
            if self.children.dirty:
                self.temp_children = []
                self.new_line()
                self.recurse(self.node)
                self.children.set(self.temp_children)

                height_dependencies = [child.height for child in self.temp_children]
                height_dependencies.append(self.children)
                self.height.set_dependencies(height_dependencies)

        assert not self.children.dirty
        for child in self.children.get():
            child.layout()

        self.has_dirty_descendants = False

        children = self.children.read(notify=self.height)
        new_height = sum([child.height.read(notify=self.height) for child in children])
        self.height.set(new_height)

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
        self.previous_word = None
        self.cursor_x = 0
        last_line = self.temp_children[-1] if self.temp_children else None
        new_line = LineLayout(self.node, self, last_line)
        self.temp_children.append(new_line)

    def word(self, node, word):
        zoom = self.zoom.read(notify=self.children)
        node_font = font(node.style, zoom, notify=self.children)
        w = node_font.measureText(word)
        self.add_inline_child(node, w, TextLayout, self.frame, word)

    def image(self, node):
        zoom = self.zoom.read(notify=self.children)
        if "width" in node.attributes:
            w = dpx(int(node.attributes["width"]), zoom)
        else:
            w = dpx(node.image.width(), zoom)
        self.add_inline_child(node, w, ImageLayout, self.frame)

    def iframe(self, node):
        zoom = self.zoom.read(notify=self.children)
        if "width" in self.node.attributes:
            w = dpx(int(self.node.attributes["width"]), zoom)
        else:
            w = IFRAME_WIDTH_PX + dpx(2, zoom)
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
            next = BlockLayout(child, self, previous, self.frame)
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
        if self.node.is_focused and "contenteditable" in self.node.attributes:
            text_nodes = [
                t for t in tree_to_list(self, []) if isinstance(t, TextLayout)
            ]
            if text_nodes:
                cmds.append(DrawCursor(text_nodes[-1], text_nodes[-1].width.get()))
            else:
                cmds.append(DrawCursor(self, 0))

        cmds = paint_visual_effects(self.node, cmds, self.self_rect())

        return cmds

    def add_inline_child(self, node, w, child_class, frame, word=None):
        width = self.width.read(notify=self.children)
        if self.cursor_x + w > width:
            self.new_line()
        line = self.temp_children[-1]
        if word:
            child = child_class(node, word, line, self.previous_word)
        else:
            child = child_class(node, line, self.previous_word, frame)
        line.children.append(child)
        self.previous_word = child
        zoom = self.zoom.read(notify=self.children)
        self.cursor_x += w + font(node.style, zoom, notify=self.children).measureText(
            " "
        )
