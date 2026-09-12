import skia
from constants import *


def parse_color(color):
    if color.startswith("#") and len(color) == 7:
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)

        return skia.Color(r, g, b)
    elif color.startswith("#") and len(color) == 9:
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        a = int(color[7:9], 16)

        return skia.Color(r, g, b, a)
    elif color in NAMED_COLORS:
        return parse_color(NAMED_COLORS[color])
    else:
        return skia.ColorBLACK


def linespace(font):
    metrics = font.getMetrics()
    return metrics.fDescent - metrics.fAscent


FONTS = {}


def get_font(size, weight, style):
    key = (size, weight, style)
    if key not in FONTS:
        if weight == "bold":
            skia_weight = skia.FontStyle.kBold_Weight
        else:
            skia_weight = skia.FontStyle.kNormal_Weight

        if style == "italic":
            skia_style = skia.FontStyle.kItalic_Slant
        else:
            skia_style = skia.FontStyle.kUpright_Slant

        skia_width = skia.FontStyle.kNormal_Width
        style_info = skia.FontStyle(skia_weight, skia_width, skia_style)

        font = skia.Typeface("Arial", style_info)
        # f = font.Font(size=size, weight=weight, slant=style)
        # label = tkinter.Label(font=f)
        FONTS[key] = font

    return skia.Font(FONTS[key], size)


def dpx(css_px, zoom):
    return css_px * zoom


def font(style, zoom):
    weight = style["font-weight"]
    variant = style["font-style"]
    size = float(style["font-size"][:-2]) * 0.75
    font_size = dpx(size, zoom)

    return get_font(font_size, weight, variant)

def get_tabindex(node):
    tabindex = int(node.attributes.get("tabindex", "9999999"))
    return 9999999 if tabindex == 0 else tabindex

def is_focusable(node):
    if get_tabindex(node) < 0:
        return False
    elif "tabindex" in node.attributes:
        return True
    else:
        return node.tag in ["input", "button", "a"]


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


def parse_transform(transform_str):
    if transform_str.find("translate(") < 0:
        return None
    left_paren = transform_str.find("(")
    right_paren = transform_str.find(")")
    x_px, y_px = transform_str[left_paren + 1 : right_paren].split(",")
    return (float(x_px.strip()[:-2]), float(y_px.strip()[:-2]))
