from css_parser import *
from html_parser import *

DEFAULT_STYLE_SHEET = CSSParser(open("browser.css").read()).parse()

class Tab:
    def __init__(self, tab_height):
        self.history = []
        self.display_list = []
        self.scroll = 0
        self.url = None
        self.tab_height = tab_height

        # print("fonts: ", font.families())
        self.bi_times = font.Font(
            family="Times",
            size=16,
            weight="bold",
            slant="italic",
        )

    def scrollup(self):
        self.scroll = max(0, self.scroll - SCROLL_STEP)

    def scrolldown(self):
        max_y = max(self.document.height + 2 * VSTEP - self.tab_height, 0)
        self.scroll = min(self.scroll + SCROLL_STEP, max_y)

    def draw(self, canvas, offset):
        for cmd in self.display_list:
            if cmd.rect.top > self.scroll + self.tab_height:
                continue
            if cmd.rect.bottom < self.scroll:
                continue
            cmd.execute(self.scroll - offset, canvas)

    def load(self, url):
        self.history.append(url)
        self.url = url
        body = url.request()
        if url.scheme == "view-source":
            self.canvas.create_text(10, 10, text=body, anchor="nw")
        else:
            self.nodes = HTMLParser(body).parse()
            # print_tree(self.nodes)
            rules = DEFAULT_STYLE_SHEET.copy()
            links = [
                node.attributes["href"]
                for node in tree_to_list(self.nodes, [])
                if isinstance(node, Element)
                and node.tag == "link"
                and node.attributes["rel"] == "stylesheet"
                and "href" in node.attributes
            ]
            for link in links:
                style_url = url.resolve(link)
                try:
                    style_body = style_url.request()
                except:
                    continue
                rules.extend(CSSParser(style_body).parse())
            style(self.nodes, sorted(rules, key=cascade_priority))
            self.document = DocumentLayout(self.nodes)
            self.document.layout()
            self.display_list = []
            paint_tree(self.document, self.display_list)

    def click(self, x, y):
        # x, y = e.x, e.y

        y += self.scroll

        objs = [
            obj
            for obj in tree_to_list(self.document, [])
            if obj.x <= x < obj.x + obj.width and obj.y <= y < obj.y + obj.height
        ]

        if not objs:
            return
        elt = objs[-1].node

        while elt:
            if isinstance(elt, Text):
                pass
            elif elt.tag == "a" and "href" in elt.attributes:
                url = self.url.resolve(elt.attributes["href"])
                return self.load(url)
            elt = elt.parent

    def go_back(self):
        if len(self.history) > 1:
            self.history.pop()
            back = self.history.pop()
            self.load(back)

