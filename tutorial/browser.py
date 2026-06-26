import ctypes
import sdl2
import skia
from url import URL
from html_parser import *
from css_parser import *
from tab import Tab
from chrome import Chrome

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
                    browser.handle_enter()
                elif event.key.keysym.sym == sdl2.SDLK_DOWN:
                    browser.handle_down()
            elif event.type == sdl2.SDL_TEXTINPUT:
                browser.handle_key(event.text.text.decode('utf8'))


class Browser:
    def __init__(self):
        self.tabs = []
        self.active_tab = None
        self.sdl_window = sdl2.SDL_CreateWindow(b"Browser",
            sdl2.SDL_WINDOWPOS_CENTERED, sdl2.SDL_WINDOWPOS_CENTERED,
            WIDTH, HEIGHT, sdl2.SDL_WINDOW_SHOWN
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

    def handle_up(self, e):
        self.active_tab.scrollup()
        self.draw()

    def handle_down(self, e):
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

    def handle_key(self, e):
        if len(e.char) == 0:
            return
        if not (0x20 <= ord(e.char) < 0x7F):
            return
        if self.chrome.keypress(e.char):
            self.draw()
        elif self.focus == 'content':
            self.active_tab.keypress(e.char)
            self.draw()

    def handle_enter(self, e):
        self.chrome.enter()
        self.draw()

    def draw(self):
        self.canvas.delete("all")
        self.active_tab.draw(self.canvas, self.chrome.bottom)

        for cmd in self.chrome.paint():
            cmd.execute(0, self.canvas)

    def new_tab(self, url):
        new_tab = Tab(HEIGHT - self.chrome.bottom)
        new_tab.load(url)
        self.active_tab = new_tab
        self.tabs.append(new_tab)
        self.draw()


if __name__ == "__main__":
    import sys

    sdl2.SDL_Init(sdl2.SDL_INIT_EVENTS)
    browser = Browser()
    if len(sys.argv) > 1:
        url = URL(sys.argv[1])
        browser.new_tab(url)
    else:
        browser.new_tab(URL("file://" + DEFAULT_FILE))

    mainloop(browser)
    # tkinter.mainloop()
