import ctypes
import sys
import sdl2
import skia

if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

from url import URL
from html_parser import *
from css_parser import *
from tab import Tab
from chrome import Chrome
from utils import *

def mainloop(browser):
    event = sdl2.SDL_Event()
    while True:
        while sdl2.SDL_PollEvent(ctypes.byref(event)) != 0:
            if event.type == sdl2.SDL_QUIT:
                browser.handle_quit()
                sdl2.SDL_Quit()
                sys.exit()
            elif event.type == sdl2.SDL_MOUSEBUTTONUP:
                browser.handle_click(event.button)
            elif event.type == sdl2.SDL_KEYDOWN:
                if event.key.keysym.sym == sdl2.SDLK_RETURN:
                    browser.handle_enter(event)
                elif event.key.keysym.sym == sdl2.SDLK_DOWN:
                    browser.handle_down()
                elif event.key.keysym.sym == sdl2.SDLK_UP:
                    browser.handle_up()
            elif event.type == sdl2.SDL_TEXTINPUT:
                browser.handle_key(event.text.text.decode('utf8'))


class Browser:
    def __init__(self):
        if sdl2.SDL_BYTEORDER == sdl2.SDL_BIG_ENDIAN:
            self.RED_MASK = 0xff000000
            self.GREEN_MASK = 0x00ff0000
            self.BLUE_MASK = 0x0000ff00
            self.ALPHA_MASK = 0x000000ff
        else:
            self.RED_MASK = 0x000000ff
            self.GREEN_MASK = 0x0000ff00
            self.BLUE_MASK = 0x00ff0000
            self.ALPHA_MASK = 0xff000000

        self.tabs = []
        self.active_tab = None
        self.focus = None
        self.sdl_window = sdl2.SDL_CreateWindow(b"Browser",
            sdl2.SDL_WINDOWPOS_CENTERED, sdl2.SDL_WINDOWPOS_CENTERED,
            WIDTH, HEIGHT, sdl2.SDL_WINDOW_SHOWN
        )
        self.root_surface = skia.Surface.MakeRaster(
            skia.ImageInfo.Make(
                WIDTH, HEIGHT,
                ct=skia.kRGBA_8888_ColorType, 
                at=skia.kUnpremul_AlphaType
            )
        )
        # self.window = tkinter.Tk()
        # self.canvas = tkinter.Canvas(
        #     self.window, width=WIDTH, height=HEIGHT, bg="white"
        # )
        # self.canvas.pack()
        # self.window.bind("<Up>", self.handle_up)
        # self.window.bind("<Down>", self.handle_down)
        # self.window.bind("<Button-1>", self.handle_click)
        # self.window.bind("<Key>", self.handle_key)
        # self.window.bind("<Return>", self.handle_enter)

        self.chrome = Chrome(self)

    def handle_quit(self):
        sdl2.SDL_DestroyWindow(self.sdl_window)

    def handle_up(self):
        self.active_tab.scrollup()
        self.draw()

    def handle_down(self):
        self.active_tab.scrolldown()
        self.draw()

    def handle_click(self, e):
        if e.y < self.chrome.bottom:
            self.focus = None
            self.chrome.click(e.x, e.y)
        else:
            self.focus = "content"
            self.chrome.blur()
            tab_y = e.y - self.chrome.bottom
            self.active_tab.click(e.x, tab_y)
        self.draw()

    def handle_key(self, char):
        if len(char) == 0:
            return
        if not (0x20 <= ord(char) < 0x7F):
            return
        if self.chrome.keypress(char):
            self.draw()
        elif self.focus == 'content':
            self.active_tab.keypress(char)
            self.draw()

    def handle_enter(self):
        self.chrome.enter()
        self.draw()

    def draw(self):
        canvas = self.root_surface.getCanvas()
        canvas.clear(skia.ColorWHITE)

        self.active_tab.draw(canvas, self.chrome.bottom)

        for cmd in self.chrome.paint():
            cmd.execute(0, canvas)

        skia_image = self.root_surface.makeImageSnapshot()
        skia_bytes = skia_image.tobytes()
        depth = 32 # Bits per pixel
        pitch = 4 * WIDTH # Bytes per row
        sdl_surface = sdl2.SDL_CreateRGBSurfaceFrom(
            skia_bytes, WIDTH, HEIGHT, depth, pitch,
            self.RED_MASK, self.GREEN_MASK,
            self.BLUE_MASK, self.ALPHA_MASK
        )
        rect = sdl2.SDL_Rect(0, 0, WIDTH, HEIGHT)
        window_surface = sdl2.SDL_GetWindowSurface(self.sdl_window)
        # SDL_BlitSurface is what actually does the copy.
        sdl2.SDL_BlitSurface(sdl_surface, rect, window_surface, rect)
        sdl2.SDL_UpdateWindowSurface(self.sdl_window)

    def new_tab(self, url):
        new_tab = Tab(HEIGHT - self.chrome.bottom)
        new_tab.load(url)
        self.active_tab = new_tab
        self.tabs.append(new_tab)
        self.draw()


if __name__ == "__main__":
    sdl2.SDL_Init(sdl2.SDL_INIT_EVENTS)
    browser = Browser()
    if len(sys.argv) > 1:
        url = URL(sys.argv[1])
        browser.new_tab(url)
    else:
        browser.new_tab(URL("file://" + DEFAULT_FILE))

    mainloop(browser)
    # tkinter.mainloop()
