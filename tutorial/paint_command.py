from utils import *

class PaintCommand:
    def __init__(self, rect):
        self.rect = rect
        self.children = []

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


def paint_outline(node, cmds, rect, zoom):
    outline = parse_outline(node.style.get("outline"))
    if not outline:
        return
    thickness, color = outline
    cmds.append(DrawOutline(rect, color, dpx(thickness, zoom)))
