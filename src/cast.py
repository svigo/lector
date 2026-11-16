"""Transmisión del texto a un Chromecast / Android TV (sin Qt).

El lector sirve una página web en la red local y le pide al Chromecast que la
abra con DashCast. La página consulta /state para seguir el scroll del visor.
"""
import json
import socket
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

PORT = 8765

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Lector</title>
<style>
  html, body { margin: 0; background: #111; color: #EEE; }
  body { overflow: hidden; }
  #txt { font: 34px/1.6 Georgia, serif; padding: 40px 8vw 60vh; }
  p { margin: 0 0 0.9em; white-space: pre-wrap; }
  mark { background: #FFE566; color: #111; }
  mark.a { background: #66BBFF; } mark.b { background: #FF9966; }
  mark.current { background: #FF4444; color: #FFF; }
</style></head>
<body><div id="txt"></div>
<script>
let ver = -1, paras = [], target = 0, cur = 0;
function esc(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function render(text, marks) {
  const box = document.getElementById('txt'); box.innerHTML = ''; paras = [];
  let off = 0;
  for (const chunk of text.split('\\n')) {
    const start = off, end = off + chunk.length;
    let html = '', pos = start;
    for (const [s, e, cls] of marks) {
      if (e <= start || s >= end) continue;
      const a = Math.max(s, start), b = Math.min(e, end);
      html += esc(text.slice(pos, a)) + '<mark class="' + cls + '">' + esc(text.slice(a, b)) + '</mark>';
      pos = b;
    }
    html += esc(text.slice(pos, end));
    const p = document.createElement('p'); p.innerHTML = html || '&nbsp;';
    box.appendChild(p); paras.push([start, end, p]);
    off = end + 1;
  }
}
function topFor(block, frac) {
  const it = paras[Math.min(block, paras.length - 1)];
  if (!it) return 0;
  return it[2].offsetTop + frac * it[2].offsetHeight - 40;
}
async function poll() {
  try {
    const st = await (await fetch('/state')).json();
    if (st.v !== ver) {
      const d = await (await fetch('/text')).json();
      render(d.text, d.marks); ver = st.v;
    }
    target = Math.max(0, topFor(st.b, st.f));
  } catch (e) {}
  setTimeout(poll, 250);
}
function animate() {  // sigue al objetivo de a poco; saltos de más de una pantalla van directo
  const d = target - cur;
  if (Math.abs(d) > window.innerHeight) cur = target;
  else cur += d * 0.06;
  window.scrollTo(0, cur);
  requestAnimationFrame(animate);
}
poll(); animate();
</script></body></html>
"""


class _State:
    def __init__(self):
        self.version = 0
        self.text = ''
        self.marks = []   # [(start, end, clase_css)]
        self.block = 0    # párrafo que está arriba de todo en el visor
        self.frac = 0.0   # cuánto de ese párrafo ya pasó (0..1)


class _Handler(BaseHTTPRequestHandler):
    state: _State = None

    def do_GET(self):
        st = self.state
        if self.path == '/':
            self._send(PAGE.encode(), 'text/html; charset=utf-8')
        elif self.path == '/state':
            self._send(json.dumps({'v': st.version, 'b': st.block, 'f': st.frac}).encode(), 'application/json')
        elif self.path == '/text':
            self._send(json.dumps({'text': st.text, 'marks': st.marks}).encode(), 'application/json')
        else:
            self.send_error(404)

    def _send(self, body: bytes, ctype: str):
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def discover(timeout: float = 6) -> list:
    """Devuelve la lista de nombres de los dispositivos Cast de la red."""
    import pychromecast
    casts, browser = pychromecast.get_chromecasts(timeout=timeout)
    browser.stop_discovery()
    return sorted(c.cast_info.friendly_name for c in casts)


def _local_ip_towards(host: str) -> str:
    """IP de este PC en la interfaz que llega a `host`."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((host, 8009))
        return s.getsockname()[0]


class CastSession:
    """Servidor web + DashCast en un Chromecast. Métodos bloqueantes: llamar fuera del hilo de UI.

    Vigila qué app tiene abierta la tele: si DashCast se cierra solo (la tele vuelve al
    inicio, p. ej. por inactividad) lo reabre; si se abre otra app, llama a `on_ended`.
    `on_ended` se llama desde un hilo de pychromecast.
    """

    def __init__(self, on_ended=None):
        self.state = _State()
        self.on_ended = on_ended
        self._server = None
        self._cast = None
        self._browser = None
        self._dash = None
        self._url = None
        self._ended = False
        self._relaunches = []   # timestamps de reaperturas recientes
        self._grace_until = 0   # hasta cuándo ignorar "sin app": DashCast tarda ~5 s en abrir

    def new_cast_status(self, status):
        """Listener de pychromecast: se llama cada vez que cambia la app de la tele."""
        from pychromecast.config import APP_BACKDROP, APP_DASHCAST
        if self._ended or status is None or status.app_id == APP_DASHCAST:
            return
        if status.app_id in (None, APP_BACKDROP):
            now = time.monotonic()
            if now < self._grace_until:
                return
            self._relaunches = [t for t in self._relaunches if now - t < 120]
            if len(self._relaunches) < 3:   # evita un bucle si la tele la cierra al instante
                self._relaunches.append(now)
                self._grace_until = now + 15
                self._dash.load_url(self._url, force=True)
                return
        self._ended = True                  # otra app en la tele, o demasiados cierres
        if self.on_ended:
            self.on_ended()

    def start(self, device_name: str):
        import pychromecast
        from pychromecast.controllers.dashcast import DashCastController

        casts, self._browser = pychromecast.get_listed_chromecasts(
            friendly_names=[device_name], timeout=8)
        if not casts:
            self._browser.stop_discovery()
            raise RuntimeError(f'No se encontró "{device_name}" en la red')
        self._cast = casts[0]
        self._cast.wait(timeout=10)

        handler = type('Handler', (_Handler,), {'state': self.state})
        self._server = ThreadingHTTPServer(('0.0.0.0', PORT), handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

        ip = _local_ip_towards(self._cast.cast_info.host)
        self._url = f'http://{ip}:{PORT}/'
        self._dash = DashCastController()
        self._cast.register_handler(self._dash)
        self._grace_until = time.monotonic() + 15
        self._dash.load_url(self._url, force=True)
        self._cast.socket_client.receiver_controller.register_status_listener(self)

    def stop(self):
        self._ended = True
        if self._cast:
            try:
                self._cast.quit_app()
            except Exception:
                pass
            self._cast = None
        if self._browser:
            self._browser.stop_discovery()
            self._browser = None
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    # --- Actualizaciones desde el visor (baratas, sin red) ---

    def set_content(self, text: str, marks: list):
        self.state.text = text
        self.state.marks = marks
        self.state.version += 1

    def set_top(self, block: int, frac: float):
        self.state.block = block
        self.state.frac = frac
