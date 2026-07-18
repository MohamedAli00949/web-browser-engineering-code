import ctypes
import sys
import sdl2
import skia
import math
import OpenGL.GL

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

        browser.composite_raster_and_draw()
        browser.schedule_animation_frame()


def add_parent_pointers(nodes, parent=None):
    for node in nodes:
        node.parent = parent
        add_parent_pointers(node.children, node)

class Browser:
    def __init__(self):
        self.chrome = Chrome(self)
        self.composited_layers = []
        self.draw_list = []

        self.sdl_window = sdl2.SDL_CreateWindow(b"Browser",
            sdl2.SDL_WINDOWPOS_CENTERED,
            sdl2.SDL_WINDOWPOS_CENTERED,
            WIDTH, HEIGHT,
            sdl2.SDL_WINDOW_SHOWN | sdl2.SDL_WINDOW_OPENGL)
        self.gl_context = sdl2.SDL_GL_CreateContext(
            self.sdl_window)
        print(("OpenGL initialized: vendor={}," + \
            "renderer={}").format(
            OpenGL.GL.glGetString(OpenGL.GL.GL_VENDOR),
            OpenGL.GL.glGetString(OpenGL.GL.GL_RENDERER)))
        self.tab_surface = None

        self.tabs = []
        self.active_tab = None
        self.focus = None
        self.active_bar = ""
        self.lock = threading.Lock()
        self.active_tab_url = None
        self.active_tab_scroll = 0

        self.measure = MeasureTime()
        threading.current_thread().name = "Browser Thread"

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

        self.animation_timer = None

        self.needs_animation_frame = False
        self.needs_raster_and_draw = False

        self.active_tab_height = 0
        self.active_tab_display_list = None

        self.skia_context = skia.GrDirectContext.MakeGL()
        self.root_surface = skia.Surface.MakeFromBackendRenderTarget(
            self.skia_context,
            skia.GrBackendRenderTarget(
                WIDTH, HEIGHT,
                0, 0,
                skia.GrGLFramebufferInfo(
                    0, OpenGL.GL.GL_RGBA8
                )
            ),
            skia.kBottomLeft_GrSurfaceOrigin,
            skia.kRGBA_8888_ColorType,
            skia.ColorSpace.MakeSRGB()
        )
        self.chrome_surface = skia.Surface.MakeRenderTarget(
            self.skia_context, skia.Budgeted.kNo,
            skia.ImageInfo.MakeN32Premul(
                WIDTH, math.ceil(self.chrome.bottom)),
        )
        assert self.root_surface is not None
        assert self.chrome_surface is not None

    def render(self):
        if self.active_tab.loaded:
            self.active_tab.run_animation_frame(self.active_tab_scroll)

    def clamp_scroll(self, scroll):
        height = self.active_tab_height
        maxscroll = height - (HEIGHT - self.chrome.bottom)
        return max(0, min(scroll, maxscroll))

    def commit(self, tab, data):
        self.lock.acquire(blocking=True)
        if tab == self.active_tab:
            self.active_tab_url = data.url
            if data.scroll is not None:
                self.active_tab_scroll = data.scroll
                # self.active_tab.scroll = data.scroll
            # else:
            #     self.active_tab_scroll = 0
            #     self.active_tab.scroll = 0

            self.active_tab_height = data.height if data.height is not None else 0

            if data.display_list is not None:
                self.active_tab_display_list = data.display_list
            # else:
            #     self.active_tab_display_list = []

            # self.animation_timer = None
            self.set_needs_raster_and_draw()
        self.lock.release()

    def handle_quit(self):
        self.measure.finish()
        for tab in self.tabs:
            tab.task_runner.set_needs_quit()
        sdl2.SDL_GL_DeleteContext(self.gl_context)
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
            self.set_needs_raster_and_draw()
        else:
            if self.focus != "content":
                self.focus = "content"
                self.chrome.focus = None
                self.set_needs_raster_and_draw()
            # url = self.active_tab.url
            self.chrome.blur()
            tab_y = e.y - self.chrome.bottom
            task = Task(self.active_tab.click, e.x, tab_y)
            self.active_tab.task_runner.schedule_task(task)
        #     if self.active_tab.url != url:
        #         self.raster_chrome()
        #     self.raster_tab()
        # self.draw()
        self.lock.release()

    def handle_key(self, char):
        self.lock.acquire(blocking=True)
        if len(char) == 0:
            return
        if not (0x20 <= ord(char) < 0x7F):
            return

        if self.chrome.keypress(char):
            self.set_needs_raster_and_draw()
        elif self.focus == 'content':
            task = Task(self.active_tab.keypress, char)
            self.active_tab.task_runner.schedule_task(task)
        self.lock.release()

    def handle_enter(self):
        self.lock.acquire(blocking=True)
        if self.chrome.enter():
            self.set_needs_raster_and_draw()
        self.lock.release()

    def raster_tab(self):
        # if self.active_tab_height == None:
        #     return

        # if not self.tab_surface or self.active_tab_height != self.tab_surface.height():
        #     self.tab_surface = skia.Surface.MakeRenderTarget(
        #         self.skia_context, skia.Budgeted.kNo,
        #         skia.ImageInfo.MakeN32Premul(
        #             WIDTH, self.active_tab_height
        #         ))

        # canvas = self.tab_surface.getCanvas()
        # canvas.clear(skia.ColorWHITE)
        # for cmd in self.active_tab_display_list:
        #     cmd.execute(self.active_tab_scroll, canvas)
        for composited_layer in self.composited_layers:
            composited_layer.raster()

    def raster_chrome(self):
        canvas = self.chrome_surface.getCanvas()
        canvas.clear(skia.ColorWHITE)
        for cmd in self.chrome.paint():
            cmd.execute(0, canvas)

    def draw(self):
        canvas = self.root_surface.getCanvas()
        canvas.clear(skia.ColorWHITE)

        # tab_rect = skia.Rect.MakeLTRB(
        #     0, self.chrome.bottom, WIDTH, HEIGHT)
        tab_offset = self.chrome.bottom - self.active_tab.scroll
        canvas.save()
        # canvas.clipRect(tab_rect)
        canvas.translate(0, tab_offset)
        for item in self.draw_list:
            item.execute(canvas)
        canvas.restore()

        chrome_rect = skia.Rect.MakeLTRB(
            0, 0, WIDTH, self.chrome.bottom)
        canvas.save()
        canvas.clipRect(chrome_rect)
        self.chrome_surface.draw(canvas, 0, 0)
        canvas.restore()

        # skia_image = self.root_surface.makeImageSnapshot()
        # skia_bytes = skia_image.tobytes()

        # depth = 32 # Bits per pixel
        # pitch = 4 * WIDTH # Bytes per row
        # sdl_surface = sdl2.SDL_CreateRGBSurfaceFrom(
        #     skia_bytes, WIDTH, HEIGHT, depth, pitch,
        #     self.RED_MASK, self.GREEN_MASK,
        #     self.BLUE_MASK, self.ALPHA_MASK)

        # rect = sdl2.SDL_Rect(0, 0, WIDTH, HEIGHT)
        # window_surface = sdl2.SDL_GetWindowSurface(self.sdl_window)
        # sdl2.SDL_BlitSurface(sdl_surface, rect, window_surface, rect)
        # sdl2.SDL_UpdateWindowSurface(self.sdl_window)
        self.root_surface.flushAndSubmit()
        sdl2.SDL_GL_SwapWindow(self.sdl_window)

    def set_needs_raster_and_draw(self):
        self.needs_raster_and_draw = True

    def composite_raster_and_draw(self):
        self.lock.acquire(blocking=True)
        if not self.needs_raster_and_draw:
            self.lock.release()
            return
        self.measure.time('raster/draw')
        self.raster_chrome()
        self.raster_tab()
        self.draw()
        self.measure.stop('raster/draw')
        self.needs_raster_and_draw = False
        self.lock.release()

    def schedule_animation_frame(self):
        def callback():
            self.lock.acquire(blocking=True)
            scroll = self.active_tab_scroll
            self.needs_animation_frame = False
            active_tab = self.active_tab
            self.lock.release()
            task = Task(active_tab.run_animation_frame, scroll)
            active_tab.task_runner.schedule_task(task)
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
        self.active_tab_url = None
        self.needs_animation_frame = True
        self.animation_timer = None

    def new_tab(self, url):
        self.lock.acquire(blocking=True)
        self.new_tab_internal(url)
        self.lock.release()

    def new_tab_internal(self, url):
        new_tab = Tab(self, HEIGHT - self.chrome.bottom)
        self.tabs.append(new_tab)
        self.set_active_tab(new_tab)
        self.schedule_load(url)

        # if not new_tab.task_runner_thread.is_alive():
        #     new_tab.task_runner_thread.start()

    def composite(self):
        add_parent_pointers(self.active_tab_display_list)
        self.composited_layers = []
        all_commands = []
        for cmd in self.active_tab_display_list:
            all_commands = tree_to_list(cmd, all_commands)
        paint_commands = [cmd for cmd in all_commands if isinstance(cmd, PaintCommand)]
        for cmd in paint_commands:
            layer = CompositedLayer(self.skia_context, cmd)
            self.composited_layers.append(layer)

    def paint_draw_list(self):
        new_effects = {}
        self.draw_list = []
        for composited_layer in self.composited_layers:
            current_effect = DrawCompositedLayer(composited_layer)
            if not composited_layer.display_items: continue
            parent = composited_layer.display_items[0].parent
            while parent:
                if parent in new_effects:
                    new_parent = new_effects[parent]
                    new_parent.children.append(current_effect)
                    break
                else:
                    current_effect = parent.clone(current_effect)
                    new_effects[parent] = current_effect
                    parent = parent.parent
            if not parent:
                self.draw_list.append(current_effect)

    # def composite_raster_and_draw(self):
    #     # self.lock.acquire(blocking=True)
    #     # if not self.needs_composite and not self.needs_raster and not self.needs_draw:
    #     #     self.lock.release()
    #     #     return

    #     # self.measure.time('composite/raster/draw')

    #     # start_time = time.time()
    #     # if self.needs_composite:
    #     #     self.measure.time('composite')
    #     #     self.composite()
    #     #     self.measure.stop('composite')
    #     # if self.needs_raster:
    #     #     self.measure.time('raster')
    #     #     self.raster_chrome()
    #     #     self.raster_tab()
    #     #     self.measure.stop('raster')
    #     # if self.needs_draw:
    #     #     self.measure.time('draw')
    #     #     self.paint_draw_list()
    #     #     self.draw()
    #     #     self.measure.stop('draw')

    #     # self.measure.stop('composite/raster/draw')
    #     # self.needs_composite = False
    #     # self.needs_raster = False
    #     # self.needs_draw = False
    #     # self.lock.release()

    #     self.composite()
    #     self.raster_chrome()
    #     self.raster_tab()
    #     self.paint_draw_list()
    #     self.draw()


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
