"""Marginalia en el escritorio: la misma app, en una ventanita siempre a la vista.

No hay una segunda app aca adentro. Esto abre `index.html?widget=1` en un
WebView2 sin bordes y le presta lo que una pagina web no puede tener en
Windows: quedarse arriba de todo, un atajo global, un icono en la bandeja y una
posicion que sobrevive al reinicio. Todo lo demas -- apuntes, materias, fotos,
login y sync con Supabase -- es el mismo codigo que corre en el celu.

El perfil del WebView2 vive en LOCALAPPDATA y es propio: la sesion se inicia una
vez desde el widget y despues sincroniza como cualquier otro dispositivo.

    py desktop/widget.py            la app publicada en GitHub Pages
    py desktop/widget.py --local    el index.html de al lado, para probar cambios
    py desktop/widget.py --hidden   arranca guardado en la bandeja
"""
import ctypes
import json
import logging
import os
import sys
import threading
import webbrowser
from ctypes import wintypes

import webview

APP_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(APP_DIR)
DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", APP_DIR), "Marginalia")
CONFIG_PATH = os.path.join(DATA_DIR, "widget.json")
STORAGE_DIR = os.path.join(DATA_DIR, "webview")
ICON_PATH = os.path.join(REPO_DIR, "apple-touch-icon.png")
LOCAL_PORT = 8731

DEFAULTS = {
    "url": "https://gr8kaio.github.io/marginalia/?widget=1",
    "hotkey": "ctrl+alt+n",
    "on_top": True,
    "anchored": False,  # pegado al fondo del escritorio en vez de flotando
    "x": None,          # None = arriba a la derecha del monitor principal
    "y": None,
    "width": 340,
    "height": 560,
}

log = logging.getLogger("marginalia")

# La ventana no viaja dentro del objeto js_api ni de ninguna estructura que
# pywebview inspeccione: tocar sus internos desde el hilo equivocado cuelga la
# app entera. Vive aca y cada quien la pide cuando la necesita.
_win = None
_cfg = dict(DEFAULTS)
_save_timer = None
_folded_height = None
# pywebview recuerda el `hidden` del arranque y nunca lo toca de nuevo, asi que
# preguntarle si esta a la vista devuelve siempre lo mismo: lo contamos aparte.
_visible = True
_hwnd = None       # ver find_own_window(): se busca una vez y se recuerda
_u32 = None        # user32 con las firmas ya declaradas


# --------------------------------------------------------------------------
# configuracion
# --------------------------------------------------------------------------
def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            saved = json.load(fh)
        cfg.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return cfg


def save_config() -> None:
    """Guardado diferido: mover la ventana dispara un evento por pixel."""
    global _save_timer
    if _save_timer is not None:
        _save_timer.cancel()
    _save_timer = threading.Timer(1.5, _write_config)
    _save_timer.daemon = True
    _save_timer.start()


def _write_config() -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(_cfg, fh, indent=2)
    except OSError as e:
        log.warning("no se pudo guardar la config: %s", e)


def default_position(width, height):
    """Arriba a la derecha, con aire para la barra de tareas."""
    u32 = ctypes.windll.user32
    u32.SetProcessDPIAware()
    screen_w = u32.GetSystemMetrics(0)
    return max(0, screen_w - width - 28), 60


# --------------------------------------------------------------------------
# anclar al escritorio
#
# Anclado, el widget se queda en el fondo del orden de ventanas: no tapa nada,
# no sale en Alt+Tab, y cualquier cosa que abras le pasa por encima. Pero sigue
# siendo una ventana comun, y eso es todo el punto -- se clickea y se escribe.
#
# El primer intento fue colgarla del escritorio con SetParent al Progman, como
# los fondos animados. Se veia hermoso y aparecia con Win+D, pero Windows no le
# manda ni un click ni una tecla a lo que vive en esa capa: un widget de notas
# donde no se puede escribir. Este camino cambia esa gracia por poder usarlo.
#
# Lo unico que hace falta es insistir: cuando otra ventana pasa al frente, la
# nuestra vuelve al fondo. De eso se encarga el hook de EVENT_SYSTEM_FOREGROUND.
# --------------------------------------------------------------------------
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
HWND_BOTTOM = 1
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT = 0x0000

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def user32():
    """user32 con las firmas declaradas.

    Sin argtypes, ctypes manda los HWND como enteros de 32 bits y en 64 bits eso
    los corta: la funcion recibe un handle que no existe, no falla, y no hace
    nada. Sintoma exacto: el anclaje "anda" y la ventana no se mueve de lugar.
    """
    global _u32
    if _u32 is not None:
        return _u32
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.FindWindowW.restype = wintypes.HWND
    u.FindWindowExW.restype = wintypes.HWND
    u.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
    u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    u.GetWindowLongW.restype = ctypes.c_long
    u.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    u.SetWindowLongW.restype = ctypes.c_long
    u.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    u.IsWindow.argtypes = [wintypes.HWND]
    _u32 = u
    return u


def find_own_window():
    """El HWND de nuestra ventana. Se busca una vez y se recuerda.

    Se llama seguido -- el hook la pide en cada cambio de ventana -- y buscarla
    por titulo no sirve: GetWindowText a una ventana de otro hilo va por
    SendMessage, y el hilo grafico suele estar esperando a que esta funcion
    termine, asi que se traba sola. La clase se lee sin mandar mensajes.

    (`window.native` de pywebview tampoco se toca: bloquea igual.)
    """
    global _hwnd
    u32 = user32()
    if _hwnd and u32.IsWindow(_hwnd):
        return _hwnd

    mine, pid = [], os.getpid()

    @WNDENUMPROC
    def visit(hwnd, _):
        out = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(out))
        if out.value != pid or not u32.IsWindowVisible(hwnd):
            return True
        cls = ctypes.create_unicode_buffer(256)
        u32.GetClassNameW(hwnd, cls, 256)
        if cls.value.startswith("WindowsForms"):
            mine.append(hwnd)
            return False
        return True

    u32.EnumWindows(visit, 0)
    _hwnd = mine[0] if mine else None
    return _hwnd


def sink_to_bottom():
    """Mandar la ventana al fondo, sin robarle el foco a nadie."""
    u32 = user32()
    hwnd = find_own_window()
    if hwnd:
        u32.SetWindowPos(hwnd, HWND_BOTTOM, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def apply_anchor(anchored):
    """Anclar al escritorio, o devolver la ventana a flotar arriba de todo."""
    u32 = user32()
    hwnd = find_own_window()
    if not hwnd:
        log.warning("no encontre la ventana para anclarla")
        return False

    exstyle = u32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if anchored:
        # Fuera de Alt+Tab: anclada no es una ventana con la que se convive.
        u32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                           (exstyle | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
        u32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        sink_to_bottom()
    else:
        u32.SetWindowLongW(hwnd, GWL_EXSTYLE, exstyle & ~WS_EX_TOOLWINDOW)
        z = HWND_TOPMOST if _cfg["on_top"] else HWND_NOTOPMOST
        u32.SetWindowPos(hwnd, z, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)

    _cfg["anchored"] = bool(anchored)
    save_config()
    log.info("anclado al escritorio: %s", _cfg["anchored"])
    return True


WINEVENTPROC = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
                                  wintypes.LONG, wintypes.LONG, wintypes.DWORD,
                                  wintypes.DWORD)
_hook = None
_hook_proc = None      # el callback tiene que sobrevivir al GC o Windows crashea


def watch_foreground():
    """Cada vez que otra ventana pasa al frente, la nuestra vuelve al fondo.

    Sin esto el anclaje dura hasta el primer click: al usar el widget Windows lo
    activa y lo sube, que es justo lo que uno quiere mientras escribe -- pero
    despues tiene que volver a su lugar solo.
    """
    global _hook, _hook_proc
    if _hook:
        return

    def on_foreground(hook, event, hwnd, id_obj, id_child, tid, when):
        if not _cfg["anchored"]:
            return
        if hwnd and hwnd != find_own_window():
            sink_to_bottom()

    u32 = user32()
    _hook_proc = WINEVENTPROC(on_foreground)
    _hook = u32.SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND,
                                None, _hook_proc, 0, 0, WINEVENT_OUTOFCONTEXT)
    if not _hook:
        log.warning("sin hook de primer plano: el anclaje se va a soltar solo")


def show_window():
    global _visible
    if _win:
        _win.show()
        _visible = True


def hide_window():
    global _visible
    if _win:
        _win.hide()
        _visible = False


# --------------------------------------------------------------------------
# lo que la pagina puede pedirle a Windows
# --------------------------------------------------------------------------
class Api:
    def hide(self):
        """La cruz del widget lo guarda; para cerrarlo de verdad esta la bandeja."""
        hide_window()

    def fold(self, folded, bar_height):
        """Colapsar deja sola la barra de titulo, como una persiana."""
        global _folded_height
        if not _win:
            return
        if folded:
            _folded_height = _cfg["height"]
            _win.resize(_cfg["width"], max(int(bar_height), 28))
        else:
            _win.resize(_cfg["width"], _folded_height or DEFAULTS["height"])
            _folded_height = None

    def open_app(self, url):
        """La app entera va al navegador de siempre, no a esta ventana."""
        webbrowser.open(url)

    def anchor(self, anchored):
        """El boton del ancla. Devuelve como quedo, no como se pidio."""
        apply_anchor(bool(anchored))
        return _cfg["anchored"]

    def state(self):
        """Lo que la barra necesita saber para dibujarse al abrir."""
        return {"anchored": _cfg["anchored"], "on_top": _cfg["on_top"],
                "hotkey": _cfg["hotkey"]}


# --------------------------------------------------------------------------
# atajo global
# --------------------------------------------------------------------------
MODS = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002,
        "shift": 0x0004, "win": 0x0008}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312


def parse_hotkey(spec):
    """De "ctrl+alt+n" a (modificadores, tecla). None si no se entiende."""
    parts = [p.strip().lower() for p in str(spec).split("+") if p.strip()]
    if not parts:
        return None
    mods, key = 0, None
    for p in parts:
        if p in MODS:
            mods |= MODS[p]
        elif len(p) == 1:
            key = ord(p.upper())
        elif p.startswith("f") and p[1:].isdigit() and 1 <= int(p[1:]) <= 24:
            key = 0x70 + int(p[1:]) - 1
        else:
            return None
    if key is None or not mods:
        return None
    return mods, key


def windows_thread(spec, on_press):
    """El hilo con loop de mensajes: el atajo global y el hook viven aca.

    Los dos lo necesitan. RegisterHotKey manda WM_HOTKEY a la cola del hilo que
    lo registro, y un WinEventHook fuera de proceso solo entrega sus avisos a un
    hilo que este bombeando mensajes. Por eso el loop corre aunque el atajo
    falle: sin el, el anclaje se soltaria con la primera ventana que abras.
    """
    u32 = ctypes.windll.user32
    combo = parse_hotkey(spec)
    if combo is None:
        log.warning("atajo ilegible, va sin atajo: %r", spec)
    else:
        mods, key = combo
        if u32.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, key):
            log.info("atajo %s registrado", spec)
        else:
            # Casi siempre es que otro programa ya se quedo con esa combinacion.
            log.warning("Windows no dio el atajo %s (ya esta tomado)", spec)

    watch_foreground()

    msg = wintypes.MSG()
    while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        if msg.message == WM_HOTKEY:
            try:
                on_press()
            except Exception as e:
                log.warning("el atajo fallo: %s", e)


def toggle_window():
    """Un atajo que solo muestra no sirve: la segunda vez tiene que esconder.

    Anclada tambien sirve para lo otro que uno quiere: la ventana aparece
    activada, arriba de lo que haya, lista para escribir. Cuando pasas a otra
    cosa, el hook la devuelve al fondo sola.
    """
    if _visible and not _cfg["anchored"]:
        hide_window()
    elif _visible:
        show_window()      # anclada: traerla al frente y darle el teclado
    else:
        show_window()


# --------------------------------------------------------------------------
# bandeja
# --------------------------------------------------------------------------
def start_tray():
    """Sin icono, una ventana escondida no tiene como volver. Devuelve si lo hay."""
    try:
        import pystray
        from PIL import Image
        image = Image.open(ICON_PATH)
    except (ImportError, OSError) as e:
        log.warning("sin icono en la bandeja: %s", e)
        return False

    def flip_on_top(icon, item):
        _cfg["on_top"] = not _cfg["on_top"]
        if _cfg["on_top"] and _cfg["anchored"]:
            # Anclado al fondo y encima de todo no pueden ser ciertos a la vez.
            apply_anchor(False)
        if _win:
            _win.on_top = _cfg["on_top"]
        save_config()

    def flip_anchor(icon, item):
        apply_anchor(not _cfg["anchored"])

    def quit_all(icon, item):
        icon.stop()
        if _win:
            _win.destroy()

    menu = pystray.Menu(
        pystray.MenuItem("Mostrar u ocultar", lambda i, it: toggle_window(), default=True),
        pystray.MenuItem("Siempre encima", flip_on_top, checked=lambda item: _cfg["on_top"]),
        pystray.MenuItem("Anclado al escritorio", flip_anchor,
                         checked=lambda item: _cfg["anchored"]),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Abrir la app entera",
                         lambda i, it: webbrowser.open(_cfg["url"].split("?")[0])),
        pystray.MenuItem("Salir", quit_all),
    )
    icon = pystray.Icon("marginalia", image, "Marginalia", menu)
    threading.Thread(target=icon.run, daemon=True).start()
    return True


# --------------------------------------------------------------------------
# arranque
# --------------------------------------------------------------------------
def claim_single_instance():
    """Una sola instancia: la segunda hace aparecer la primera y se va.

    Dos widgets no molestan por la ventana repetida sino por el atajo: lo
    registra el que llega primero y el segundo se queda mudo, respondiendo a
    nada. El puerto de control queda anotado en LOCALAPPDATA; si el archivo es
    de una instancia muerta, nadie contesta y seguimos de largo.
    """
    import socket

    port_file = os.path.join(DATA_DIR, "control.port")
    try:
        with open(port_file, encoding="utf-8") as fh:
            port = int(fh.read().strip())
        with socket.create_connection(("127.0.0.1", port), timeout=1.5) as sock:
            sock.sendall(b"show\n")
            sock.recv(16)
        return False
    except (OSError, ValueError):
        pass

    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(4)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(port_file, "w", encoding="utf-8") as fh:
        fh.write(str(server.getsockname()[1]))

    def serve():
        while True:
            try:
                conn, _ = server.accept()
                with conn:
                    conn.recv(32)
                    show_window()
                    conn.sendall(b"ok\n")
            except OSError:
                return

    threading.Thread(target=serve, daemon=True).start()
    return True


def serve_local():
    """Sirve el index.html de al lado para probar cambios sin publicarlos.

    Va por HTTP y siempre por el mismo puerto a proposito: en file:// no hay
    IndexedDB, y un puerto que cambia seria un origen distinto cada vez, o sea
    una sesion y unos apuntes nuevos en cada arranque.
    """
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class Quiet(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=REPO_DIR, **kw)

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", LOCAL_PORT), Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("sirviendo %s en el puerto %d", REPO_DIR, LOCAL_PORT)
    return "http://127.0.0.1:%d/index.html?widget=1" % LOCAL_PORT


def main():
    global _win, _cfg, _visible

    _cfg = load_config()
    os.makedirs(STORAGE_DIR, exist_ok=True)

    # Los accesos directos abren con pythonw.exe, que no tiene consola: sin este
    # archivo, un atajo que no responde o una bandeja que no aparece no dejan rastro.
    handlers = [logging.FileHandler(os.path.join(DATA_DIR, "widget.log"), encoding="utf-8")]
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )
    log.info("arrancando (pid %d)", os.getpid())

    if not claim_single_instance():
        log.info("ya habia un widget andando: le pedi que se muestre y me voy")
        return

    local = "--local" in sys.argv
    url = serve_local() if local else _cfg["url"]

    # La bandeja se decide antes que la ventana: escondida y sin icono no hay
    # forma de traerla de vuelta, asi que sin icono arranca a la vista.
    tray = start_tray()
    hidden = "--hidden" in sys.argv and tray
    if "--hidden" in sys.argv and not tray:
        log.warning("sin bandeja, la ventana arranca a la vista")
    _visible = not hidden

    x, y = _cfg["x"], _cfg["y"]
    if x is None or y is None:
        x, y = default_position(_cfg["width"], _cfg["height"])

    _win = webview.create_window(
        "Marginalia",
        url,
        js_api=Api(),
        width=_cfg["width"], height=_cfg["height"], x=x, y=y,
        min_size=(260, 44),   # colapsado tiene que entrar la barra sola y nada mas
        frameless=True,
        easy_drag=False,      # arrastra solo la barra: adentro se escribe y se selecciona
        text_select=True,
        on_top=_cfg["on_top"],
        hidden=hidden,
        background_color="#F7F6F2",
    )

    def remember_move(win_x, win_y):
        _cfg["x"], _cfg["y"] = int(win_x), int(win_y)
        save_config()

    def remember_size(width, height):
        # Colapsado la altura es la de la barra; esa no es la que hay que recordar.
        if _folded_height is not None:
            return
        _cfg["width"], _cfg["height"] = int(width), int(height)
        save_config()

    _win.events.moved += remember_move
    _win.events.resized += remember_size

    # shown corre en el hilo grafico y con la ventana ya creada: el mejor momento
    # para quedarse con el handle, y para retomar el anclaje de la vez pasada.
    def on_shown():
        find_own_window()
        if _cfg["anchored"]:
            apply_anchor(True)

    _win.events.shown += on_shown

    threading.Thread(
        target=windows_thread, args=(_cfg["hotkey"], toggle_window), daemon=True
    ).start()

    webview.start(
        private_mode=False,          # la sesion de Supabase tiene que sobrevivir al reinicio
        storage_path=STORAGE_DIR,
    )
    _write_config()


if __name__ == "__main__":
    main()
