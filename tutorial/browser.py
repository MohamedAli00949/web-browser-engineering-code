import ctypes
import sys
import sdl2
import skia
import math

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
from constants import *
from tasks import *
from measure_time import *

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
                elif event.key.keysym.sym == sdl2.SDLK_UP:
                    browser.handle_up()
            elif event.type == sdl2.SDL_TEXTINPUT:
                browser.handle_key(event.text.text.decode('utf8'))

        browser.raster_and_draw()
        browser.schedule_animation_frame()

class Browser:
    def __init__(self):
        self.measure = MeasureTime()
        self.animation_timer = None
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

        self.chrome = Chrome(self)

        self.chrome_surface = skia.Surface(WIDTH, math.ceil(self.chrome.bottom))
        self.tab_surface = None

        self.needs_raster_and_draw = False
        self.needs_animation_frame = True

        self.lock = threading.Lock()

        threading.current_thread().name = "Browser Thread"

        self.active_tab_url = None
        self.active_tab_scroll = 0
        self.active_tab_height = 0
        self.active_tab_display_list = []

    def clamp_scroll(self, scroll):
        height = self.active_tab_height
        maxscroll = height - (HEIGHT - self.chrome.bottom)
        return max(0, min(scroll, maxscroll))

    def commit(self, tab, data):
        self.lock.acquire()
        if tab == self.active_tab:
            self.active_tab_url = data.url
            if data.scroll is not None:
                self.active_tab_scroll = data.scroll
                self.active_tab.scroll = data.scroll
            else:
                self.active_tab_scroll = 0
                self.active_tab.scroll = 0

            self.active_tab_height = data.height if data.height is not None else 0

            if data.display_list is not None:
                self.active_tab_display_list = data.display_list
            else:
                self.active_tab_display_list = []

            self.animation_timer = None
            self.set_needs_raster_and_draw()
        self.lock.release()

    def handle_quit(self):
        for tab in self.tabs:
            tab.task_runner.set_needs_quit()
        sdl2.SDL_DestroyWindow(self.sdl_window)

    def handle_up(self):
        self.lock.acquire(blocking=True)

        if not self.active_tab_height:
            self.lock.release()
            return

        # task = Task(self.active_tab.scrollup)
        # self.active_tab.task_runner.schedule_task(task)
        # self.draw()

        self.active_tab_scroll = self.clamp_scroll(
            self.active_tab_scroll - SCROLL_STEP
        )


        self.set_needs_raster_and_draw()
        self.lock.release()

    def handle_down(self):
        self.lock.acquire(blocking=True)

        if not self.active_tab_height:
            self.lock.release()
            return

        # task = Task(self.active_tab.scrolldown)
        # self.active_tab.task_runner.schedule_task(task)
        # self.draw()

        self.active_tab_scroll = self.clamp_scroll(
            self.active_tab_scroll + SCROLL_STEP
        )

        self.set_needs_raster_and_draw()
        self.needs_animation_frame = True
        self.lock.release()

    def handle_click(self, e):
        self.lock.acquire(blocking=True)
        if e.y < self.chrome.bottom:
            self.focus = None
            self.chrome.click(e.x, e.y)
            self.raster_chrome()

            self.set_needs_raster_and_draw()
        else:
            self.focus = "content"
            self.chrome.blur()
            url = self.active_tab.url
            tab_y = e.y - self.chrome.bottom
            # self.active_tab.click(e.x, tab_y)
            task = Task(self.active_tab.click, e.x, tab_y)
            self.active_tab.task_runner.schedule_task(task)
            if self.active_tab.url != url:
                self.raster_chrome()
            self.raster_tab()
        self.draw()
        self.lock.release()

    def handle_key(self, char):
        self.lock.acquire(blocking=True)
        if len(char) == 0:
            return
        if not (0x20 <= ord(char) < 0x7F):
            return

        if self.chrome.keypress(char):
            self.draw()
            self.set_needs_raster_and_draw()
        elif self.focus == 'content':
            task = Task(self.active_tab.keypress, char)
            self.active_tab.task_runner.schedule_task(task)
            self.draw()
        self.lock.release()

    def handle_enter(self):
        self.lock.acquire(blocking=True)
        if self.chrome.enter():
            self.draw()

            self.set_needs_raster_and_draw()
        self.lock.release()

    def raster_tab(self):
        if not hasattr(self.active_tab, 'document'): return

        tab_height = math.ceil(
            self.active_tab.document.height + 2*VSTEP
        )

        if not self.tab_surface or tab_height != self.tab_surface.height():
            self.tab_surface = skia.Surface(WIDTH, tab_height)

        canvas = self.tab_surface.getCanvas()
        canvas.clear(skia.ColorWHITE)

    def raster_chrome(self):
        canvas = self.chrome_surface.getCanvas()
        canvas.clear(skia.ColorWHITE)

    def draw(self):
        # Ensure active_tab.scroll is not None
        if self.active_tab and self.active_tab.scroll is None:
            self.active_tab.scroll = 0
        
        canvas = self.root_surface.getCanvas()
        canvas.clear(skia.ColorWHITE)
        
        # Debug: Check if we have display list
        if self.active_tab:
            print(f"Drawing tab with display_list: {len(self.active_tab.display_list) if self.active_tab.display_list else 0} items")
            if self.active_tab.display_list:
                self.active_tab.raster(canvas, self.chrome.bottom)
            else:
                # Draw a placeholder message
                paint = skia.Paint(Color=skia.ColorBLACK, AntiAlias=True)
                font = skia.Font(skia.Typeface('Arial'), 24)
                canvas.drawString("Loading...", 50, 100, font, paint)
        else:
            # Draw a placeholder message
            paint = skia.Paint(Color=skia.ColorBLACK, AntiAlias=True)
            font = skia.Font(skia.Typeface('Arial'), 24)
            canvas.drawString("No active tab", 50, 100, font, paint)
        
        # Draw chrome
        for cmd in self.chrome.paint():
            cmd.execute(0, canvas)
        
        # Draw tab surface if it exists
        if self.active_tab and hasattr(self, 'tab_surface') and self.tab_surface:
            tab_rect = skia.Rect.MakeLTRB(0, self.chrome.bottom, WIDTH, HEIGHT)
            scroll_value = self.active_tab.scroll if self.active_tab.scroll is not None else 0
            tab_offset = self.chrome.bottom - scroll_value
            canvas.save()
            canvas.clipRect(tab_rect)
            canvas.translate(0, tab_offset)
            self.tab_surface.draw(canvas, 0, 0)
            canvas.restore()
        
        # Draw chrome surface
        chrome_rect = skia.Rect.MakeLTRB(0, 0, WIDTH, self.chrome.bottom)
        canvas.save()
        canvas.clipRect(chrome_rect)
        if hasattr(self, 'chrome_surface'):
            self.chrome_surface.draw(canvas, 0, 0)
        canvas.restore()
        
        # Update the SDL window
        skia_image = self.root_surface.makeImageSnapshot()
        skia_bytes = skia_image.tobytes()
        depth = 32
        pitch = 4 * WIDTH
        sdl_surface = sdl2.SDL_CreateRGBSurfaceFrom(
            skia_bytes, WIDTH, HEIGHT, depth, pitch,
            self.RED_MASK, self.GREEN_MASK,
            self.BLUE_MASK, self.ALPHA_MASK
        )
        rect = sdl2.SDL_Rect(0, 0, WIDTH, HEIGHT)
        window_surface = sdl2.SDL_GetWindowSurface(self.sdl_window)
        sdl2.SDL_BlitSurface(sdl_surface, rect, window_surface, rect)
        sdl2.SDL_UpdateWindowSurface(self.sdl_window)

    def set_needs_raster_and_draw(self):
        self.needs_raster_and_draw = True

    def raster_and_draw(self):
        self.lock.acquire(blocking=True)
        if not self.needs_raster_and_draw:
            self.lock.release()
            return
        self.measure.time('raster/draw')
        self.raster_chrome()
        self.raster_tab()
        self.draw()

        self.needs_raster_and_draw = False
        self.measure.stop('raster/draw')
        self.lock.release()

    def schedule_animation_frame(self):
        def callback():
            self.lock.acquire(blocking=True)
            scroll = self.active_tab_scroll
            # self.needs_animation_frame = False
            active_tab = self.active_tab
            task = Task(active_tab.run_animation_frame, scroll)
            active_tab.task_runner.schedule_task(task)
            self.lock.release()
        self.lock.acquire(blocking=True)
        if self.needs_animation_frame and not self.animation_timer:
            self.animation_timer = threading.Timer(REFRESH_RATE_SEC, callback)
            self.animation_timer.start()
        self.lock.release()

    def set_needs_animation_frame(self, tab):
        self.lock.acquire(blocking=True)
        if tab == self.active_tab:
            self.needs_animation_frame = True
        self.lock.release()

    def schedule_load(self, url, body=None):
        self.active_tab.task_runner.clear_pending_tasks()
        task = Task(self.active_tab.load, url, body)
        self.active_tab.task_runner.schedule_task(task)

    def set_active_tab(self, tab):
        self.active_tab = tab
        self.active_tab_scroll = 0
        # self.active_tab_url = None
        self.needs_animation_frame = True

    def new_tab(self, url):
        # new_tab.load(url)
        # self.active_tab = new_tab
        # self.raster_tab()
        # self.raster_chrome()
        # self.draw()
        # self.schedule_load(url)
        self.lock.acquire(blocking=True)
        self.new_tab_internal(url)
        self.lock.release()

    def new_tab_internal(self, url):
        new_tab = Tab(self, HEIGHT - self.chrome.bottom)
        self.tabs.append(new_tab)
        self.set_active_tab(new_tab)
        self.schedule_load(url)

        if not new_tab.task_runner_thread.is_alive():
            new_tab.task_runner_thread.start()

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
