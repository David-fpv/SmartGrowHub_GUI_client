#!/usr/bin/env python3
"""SmartGrowHub Control Panel — MQTT GUI for smart greenhouse management."""

import json
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
from datetime import datetime
import random
import time
from typing import Optional, Dict, Tuple

try:
    import paho.mqtt.client as mqtt
except ImportError:
    import sys
    print("Установите зависимости: pip install -r requirements.txt")
    sys.exit(1)

# ─────────────────────────── Constants ───────────────────────────

DEFAULT_BROKER       = "broker.emqx.io"
DEFAULT_PORT         = 1883
DEFAULT_DEVICE_ID    = "A0001"
DEFAULT_TOPIC_PREFIX = "/Gomel/Tar"

MODULES = [
    ("dayLight",   "Дневной свет"),
    ("uvLight",    "УФ-свет"),
    ("watering",   "Полив"),
    ("heater",     "Нагреватель"),
    ("humidifier", "Увлажнитель"),
    ("fan",        "Вентилятор"),
    ("waterPump",  "Помпа"),
    ("airFlap",    "Заслонка"),
]

SENSOR_META: Dict[str, Tuple[str, str, str]] = {
    "airTemperature":  ("🌡", "Температура воздуха",  "°C"),
    "airHumidity":     ("💧", "Влажность воздуха",    "%"),
    "pressure":        ("🔵", "Давление",              "Па"),
    "plantHeight":     ("📏", "Высота растения",       "см"),
    "light":           ("☀",  "Освещённость",          "%"),
    "soilTemperature": ("🌱", "Температура почвы",     "°C"),
    "soilMoisture":    ("💦", "Влажность почвы",       "%"),
}

C = {
    "bg":        "#0f1923",
    "panel":     "#162030",
    "card":      "#1e2d3d",
    "border":    "#263545",
    "accent":    "#4CAF50",
    "blue":      "#2196F3",
    "red":       "#f44336",
    "orange":    "#FF9800",
    "text":      "#e0e0e0",
    "dim":       "#7a8a9a",
}


def gen_ulid() -> str:
    """Generate a ULID-compatible 26-char ID."""
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    ts = int(time.time() * 1000)
    ts_part = ""
    for _ in range(10):
        ts_part = alphabet[ts & 0x1F] + ts_part
        ts >>= 5
    rand_part = "".join(random.choices(alphabet, k=16))
    return ts_part + rand_part


# ─────────────────────────── Schedule Unit Dialog ───────────────────────────

class ScheduleUnitDialog(tk.Toplevel):
    """Modal dialog for creating a new schedule unit."""

    def __init__(self, parent: tk.Tk):
        super().__init__(parent)
        self.title("Добавить единицу расписания")
        self.configure(bg=C["panel"])
        self.resizable(False, False)
        self.result: Optional[dict] = None

        self._build()
        self.grab_set()
        self.transient(parent)
        self.update_idletasks()

        # Center over parent
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        dw, dh = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry(f"+{px + (pw - dw) // 2}+{py + (ph - dh) // 2}")

    # ── helpers ──
    def _label(self, parent: tk.Widget, text: str) -> tk.Label:
        return tk.Label(parent, text=text, bg=C["panel"], fg=C["text"],
                        font=("Segoe UI", 10), anchor="w")

    def _entry(self, parent: tk.Widget, default: str = "", width: int = 16) -> tk.Entry:
        e = tk.Entry(parent, bg=C["card"], fg=C["text"], insertbackground=C["text"],
                     relief="flat", font=("Segoe UI", 10), width=width,
                     highlightthickness=1, highlightbackground=C["border"],
                     highlightcolor=C["accent"])
        e.insert(0, default)
        return e

    def _build(self):
        pad = {"padx": 12, "pady": 5}

        tk.Label(self, text="Единица расписания", bg=C["panel"], fg=C["accent"],
                 font=("Segoe UI", 12, "bold")).grid(row=0, column=0, columnspan=2,
                                                     padx=12, pady=(12, 4), sticky="w")

        # Kind
        self._label(self, "Тип (kind):").grid(row=1, column=0, sticky="w", **pad)
        self.kind_var = tk.StringVar(value="power")
        kind_cb = ttk.Combobox(self, textvariable=self.kind_var,
                               values=["power", "time"], state="readonly", width=14)
        kind_cb.grid(row=1, column=1, sticky="w", **pad)

        # Start
        self._label(self, "Начало (день T чч:мм):").grid(row=2, column=0, sticky="w", **pad)
        sf = tk.Frame(self, bg=C["panel"])
        sf.grid(row=2, column=1, sticky="w", **pad)
        self.start_day = self._entry(sf, "01", width=3)
        self.start_day.pack(side=tk.LEFT)
        tk.Label(sf, text="T", bg=C["panel"], fg=C["dim"],
                 font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=1)
        self.start_time = self._entry(sf, "00:00", width=6)
        self.start_time.pack(side=tk.LEFT)

        # End
        self._label(self, "Конец (день T чч:мм):").grid(row=3, column=0, sticky="w", **pad)
        ef = tk.Frame(self, bg=C["panel"])
        ef.grid(row=3, column=1, sticky="w", **pad)
        self.end_day = self._entry(ef, "07", width=3)
        self.end_day.pack(side=tk.LEFT)
        tk.Label(ef, text="T", bg=C["panel"], fg=C["dim"],
                 font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=1)
        self.end_time = self._entry(ef, "23:59", width=6)
        self.end_time.pack(side=tk.LEFT)

        # Magnitude
        self._label(self, "Мощность:").grid(row=4, column=0, sticky="w", **pad)
        mf = tk.Frame(self, bg=C["panel"])
        mf.grid(row=4, column=1, sticky="w", **pad)
        self.magnitude = self._entry(mf, "50", width=6)
        self.magnitude.pack(side=tk.LEFT)
        self.unit_var = tk.StringVar(value="%")
        ttk.Combobox(mf, textvariable=self.unit_var,
                     values=["%", "W", "lux"], state="readonly",
                     width=5).pack(side=tk.LEFT, padx=(4, 0))

        # Buttons
        bf = tk.Frame(self, bg=C["panel"])
        bf.grid(row=5, column=0, columnspan=2, sticky="ew", padx=12, pady=(8, 12))

        tk.Button(bf, text="Добавить", command=self._ok,
                  bg=C["accent"], fg="white", relief="flat",
                  font=("Segoe UI", 10, "bold"), padx=14, pady=5,
                  cursor="hand2").pack(side=tk.RIGHT, padx=4)
        tk.Button(bf, text="Отмена", command=self.destroy,
                  bg=C["card"], fg=C["text"], relief="flat",
                  font=("Segoe UI", 10), padx=14, pady=5,
                  cursor="hand2").pack(side=tk.RIGHT)

    def _ok(self):
        try:
            start_day = int(self.start_day.get())
            end_day   = int(self.end_day.get())
            magnitude = int(self.magnitude.get())
            if not (1 <= start_day <= 99 and 1 <= end_day <= 99):
                raise ValueError("Неверный день")
        except ValueError as e:
            messagebox.showerror("Ошибка", f"Неверный формат: {e}", parent=self)
            return

        start = f"{start_day:02d}T{self.start_time.get()}"
        end   = f"{end_day:02d}T{self.end_time.get()}"

        self.result = {
            "kind":             self.kind_var.get(),
            "schedule_unit_id": gen_ulid(),
            "interval":  {"start": start, "end": end},
            "quantity":  {"magnitude": magnitude, "unit": self.unit_var.get()},
        }
        self.destroy()


# ─────────────────────────── Module Frame ───────────────────────────

class ModuleFrame(tk.Frame):
    """Control panel for one greenhouse module (mode + schedule)."""

    def __init__(self, parent: tk.Widget, module_type: str, module_name: str,
                 app: "SmartGrowHubApp"):
        super().__init__(parent, bg=C["panel"])
        self.module_type = module_type
        self.module_name = module_name
        self.app = app
        self.schedule_units: list = []
        self.current_mode = "0"
        self._build()

    def _section(self, text: str) -> tk.LabelFrame:
        return tk.LabelFrame(self, text=text, bg=C["panel"], fg=C["accent"],
                             font=("Segoe UI", 9, "bold"), bd=1, relief="groove",
                             labelanchor="nw")

    # ── build ──
    def _build(self):
        self._build_mode_section()
        self._build_schedule_section()

    def _build_mode_section(self):
        frame = self._section("Режим работы")
        frame.pack(fill=tk.X, padx=12, pady=(12, 6))

        row = tk.Frame(frame, bg=C["panel"])
        row.pack(pady=10, padx=8)

        MODE_DEFS = [
            ("ВЫКЛ", "0", C["red"]),
            ("ВКЛ",  "1", C["accent"]),
            ("АВТО", "2", C["blue"]),
        ]
        self._mode_btns: Dict[str, tk.Button] = {}
        for label, val, color in MODE_DEFS:
            btn = tk.Button(
                row, text=label, width=9,
                command=lambda v=val, c=color: self._set_mode(v, c),
                bg=C["card"], fg=C["dim"], relief="flat",
                font=("Segoe UI", 10, "bold"),
                activebackground=color, activeforeground="white",
                cursor="hand2", pady=5,
            )
            btn.pack(side=tk.LEFT, padx=5)
            self._mode_btns[val] = (btn, color)

        self._refresh_mode_buttons()

    def _build_schedule_section(self):
        frame = self._section("Расписание")
        frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        # Listbox
        lf = tk.Frame(frame, bg=C["panel"])
        lf.pack(fill=tk.BOTH, expand=True, padx=6, pady=(6, 4))

        sb = tk.Scrollbar(lf, bg=C["card"], troughcolor=C["border"])
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.sched_list = tk.Listbox(
            lf, bg=C["card"], fg=C["text"], selectbackground=C["accent"],
            font=("Consolas", 9), relief="flat", height=7,
            yscrollcommand=sb.set, activestyle="none",
            selectforeground="white",
        )
        self.sched_list.pack(fill=tk.BOTH, expand=True)
        sb.config(command=self.sched_list.yview)

        # Buttons row
        bf = tk.Frame(frame, bg=C["panel"])
        bf.pack(fill=tk.X, padx=6, pady=(0, 8))

        tk.Button(bf, text="+ Добавить", command=self._add_unit,
                  bg=C["accent"], fg="white", relief="flat",
                  font=("Segoe UI", 9), padx=10, pady=4,
                  cursor="hand2").pack(side=tk.LEFT, padx=(0, 4))

        tk.Button(bf, text="− Удалить", command=self._delete_unit,
                  bg=C["red"], fg="white", relief="flat",
                  font=("Segoe UI", 9), padx=10, pady=4,
                  cursor="hand2").pack(side=tk.LEFT)

    # ── actions ──
    def _set_mode(self, mode: str, color: str):
        self.current_mode = mode
        self._refresh_mode_buttons()
        self.app.send_command(
            module_type=self.module_type,
            mode=mode,
            action="none",
            schedule_unit=None,
        )

    def _refresh_mode_buttons(self):
        for val, (btn, color) in self._mode_btns.items():
            if val == self.current_mode:
                btn.config(bg=color, fg="white")
            else:
                btn.config(bg=C["card"], fg=C["dim"])

    def _add_unit(self):
        dialog = ScheduleUnitDialog(self.app)
        self.app.wait_window(dialog)
        if dialog.result:
            unit = dialog.result
            self.schedule_units.append(unit)
            self._refresh_list()
            self.app.send_command(
                module_type=self.module_type,
                mode="-1",
                action="add",
                schedule_unit=unit,
            )

    def _delete_unit(self):
        sel = self.sched_list.curselection()
        if not sel:
            messagebox.showwarning("Выбор", "Выберите элемент расписания для удаления.",
                                   parent=self.app)
            return
        idx = sel[0]
        unit = self.schedule_units.pop(idx)
        self._refresh_list()
        self.app.send_command(
            module_type=self.module_type,
            mode="-1",
            action="delete",
            schedule_unit=unit,
        )

    def _refresh_list(self):
        self.sched_list.delete(0, tk.END)
        for u in self.schedule_units:
            iv   = u.get("interval", {})
            qty  = u.get("quantity", {})
            kind = u.get("kind", "")
            start = iv.get("start", "?")
            end   = iv.get("end", "?")
            mag   = qty.get("magnitude", "?")
            unit  = qty.get("unit", "")
            uid   = u.get("schedule_unit_id", "")[:8]
            self.sched_list.insert(
                tk.END,
                f"  [{uid}] {kind}: {start} → {end}   {mag}{unit}",
            )


# ─────────────────────────── Sensor Card ───────────────────────────

class SensorCard(tk.Frame):
    """Display card for a single sensor reading."""

    def __init__(self, parent: tk.Widget, icon: str, name: str, unit: str):
        super().__init__(parent, bg=C["card"], pady=7, padx=12,
                         highlightthickness=1, highlightbackground=C["border"])
        self.unit = unit

        top = tk.Frame(self, bg=C["card"])
        top.pack(fill=tk.X)
        tk.Label(top, text=f"{icon}  {name}", bg=C["card"], fg=C["dim"],
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)

        self.val_label = tk.Label(self, text="—", bg=C["card"], fg=C["text"],
                                  font=("Segoe UI", 17, "bold"))
        self.val_label.pack(anchor="w")

    def update(self, value: float):
        self.val_label.config(
            text=f"{value:.1f} {self.unit}" if isinstance(value, float) else f"{value} {self.unit}"
        )


# ─────────────────────────── Main App ───────────────────────────

class SmartGrowHubApp(tk.Tk):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.title("SmartGrowHub — Управление теплицей")
        self.geometry("1300x820")
        self.minsize(1050, 680)
        self.configure(bg=C["bg"])

        self._mqtt: Optional[mqtt.Client] = None
        self._connected = False
        self._sensor_cards: Dict[str, SensorCard] = {}
        self._module_frames: Dict[str, ModuleFrame] = {}

        self._setup_styles()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── styles ──
    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook",
                         background=C["panel"], borderwidth=0, tabmargins=0)
        style.configure("TNotebook.Tab",
                         background=C["card"], foreground=C["dim"],
                         padding=[14, 6], font=("Segoe UI", 9))
        style.map("TNotebook.Tab",
                  background=[("selected", C["accent"])],
                  foreground=[("selected", "white")])
        style.configure("TCombobox",
                         fieldbackground=C["card"], background=C["card"],
                         foreground=C["text"], selectbackground=C["accent"],
                         arrowcolor=C["dim"])
        style.map("TCombobox",
                  fieldbackground=[("readonly", C["card"])],
                  foreground=[("readonly", C["text"])])

    # ── build UI ──
    def _build_ui(self):
        self._build_toolbar()

        paned = tk.PanedWindow(self, orient=tk.HORIZONTAL,
                                bg=C["bg"], sashwidth=5, sashrelief="flat",
                                sashpad=2, handlesize=0)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 4))

        self._build_sensor_panel(paned)
        self._build_module_panel(paned)

        self._build_log_panel()

    # ── toolbar ──
    def _build_toolbar(self):
        bar = tk.Frame(self, bg=C["panel"], height=56)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)

        tk.Label(bar, text="🌱 SmartGrowHub", bg=C["panel"], fg=C["accent"],
                 font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT, padx=14)

        tk.Frame(bar, bg=C["border"], width=1).pack(side=tk.LEFT, fill=tk.Y, pady=8)

        def lbl(text: str):
            return tk.Label(bar, text=text, bg=C["panel"], fg=C["dim"],
                            font=("Segoe UI", 9))

        def field(default: str, width: int = 20):
            e = tk.Entry(bar, bg=C["card"], fg=C["text"],
                         insertbackground=C["text"], relief="flat",
                         font=("Segoe UI", 10), width=width,
                         highlightthickness=1, highlightbackground=C["border"],
                         highlightcolor=C["accent"])
            e.insert(0, default)
            return e

        lbl("Брокер:").pack(side=tk.LEFT, padx=(10, 2))
        self._broker_f = field(DEFAULT_BROKER, 18)
        self._broker_f.pack(side=tk.LEFT, padx=(0, 8))

        lbl("Порт:").pack(side=tk.LEFT, padx=(0, 2))
        self._port_f = field(str(DEFAULT_PORT), 6)
        self._port_f.pack(side=tk.LEFT, padx=(0, 8))

        lbl("Device ID:").pack(side=tk.LEFT, padx=(0, 2))
        self._device_f = field(DEFAULT_DEVICE_ID, 8)
        self._device_f.pack(side=tk.LEFT, padx=(0, 8))

        lbl("Топик:").pack(side=tk.LEFT, padx=(0, 2))
        self._topic_f = field(DEFAULT_TOPIC_PREFIX, 12)
        self._topic_f.pack(side=tk.LEFT, padx=(0, 10))

        self._conn_btn = tk.Button(
            bar, text="Подключить", command=self._toggle_connection,
            bg=C["accent"], fg="white", relief="flat",
            font=("Segoe UI", 10, "bold"), padx=14, pady=5,
            cursor="hand2", activebackground="#388E3C",
        )
        self._conn_btn.pack(side=tk.LEFT, padx=4)

        self._dot_lbl = tk.Label(bar, text="●", bg=C["panel"],
                                  fg=C["red"], font=("Segoe UI", 20))
        self._dot_lbl.pack(side=tk.LEFT, padx=(10, 2))
        self._status_lbl = tk.Label(bar, text="Отключено", bg=C["panel"],
                                     fg=C["dim"], font=("Segoe UI", 9))
        self._status_lbl.pack(side=tk.LEFT)

    # ── sensor panel ──
    def _build_sensor_panel(self, parent: tk.PanedWindow):
        frame = tk.Frame(parent, bg=C["panel"])
        parent.add(frame, minsize=240, width=270)

        tk.Label(frame, text="ДАТЧИКИ", bg=C["panel"], fg=C["accent"],
                 font=("Segoe UI", 10, "bold")).pack(pady=(14, 6), padx=12, anchor="w")

        inner = tk.Frame(frame, bg=C["panel"])
        inner.pack(fill=tk.BOTH, expand=True, padx=10)

        for sensor_type, (icon, name, unit) in SENSOR_META.items():
            card = SensorCard(inner, icon, name, unit)
            card.pack(fill=tk.X, pady=3)
            self._sensor_cards[sensor_type] = card

        self._upd_lbl = tk.Label(frame, text="Последнее обновление: —",
                                  bg=C["panel"], fg=C["dim"],
                                  font=("Segoe UI", 8))
        self._upd_lbl.pack(pady=6, padx=12, anchor="w")

    # ── module panel ──
    def _build_module_panel(self, parent: tk.PanedWindow):
        frame = tk.Frame(parent, bg=C["panel"])
        parent.add(frame, minsize=400)

        tk.Label(frame, text="УПРАВЛЕНИЕ МОДУЛЯМИ", bg=C["panel"], fg=C["accent"],
                 font=("Segoe UI", 10, "bold")).pack(pady=(14, 6), padx=12, anchor="w")

        notebook = ttk.Notebook(frame)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        for mod_type, mod_name in MODULES:
            mf = ModuleFrame(notebook, mod_type, mod_name, self)
            notebook.add(mf, text=mod_name)
            self._module_frames[mod_type] = mf

    # ── log panel ──
    def _build_log_panel(self):
        frame = tk.LabelFrame(self, text="Журнал сообщений",
                               bg=C["bg"], fg=C["dim"],
                               font=("Segoe UI", 8), bd=1, relief="groove")
        frame.pack(fill=tk.X, padx=8, pady=(0, 8))

        ctrl = tk.Frame(frame, bg=C["bg"])
        ctrl.pack(fill=tk.X, padx=6, pady=(2, 0))
        tk.Button(ctrl, text="Очистить", command=lambda: self._log_text.delete(1.0, tk.END),
                  bg=C["card"], fg=C["dim"], relief="flat",
                  font=("Segoe UI", 8), padx=6, pady=1).pack(side=tk.RIGHT)

        self._log_text = scrolledtext.ScrolledText(
            frame, height=7, bg=C["card"], fg=C["text"],
            font=("Consolas", 9), relief="flat", wrap=tk.WORD,
            insertbackground=C["text"],
        )
        self._log_text.pack(fill=tk.X, padx=6, pady=(0, 6))
        self._log_text.tag_config("IN",  foreground="#4CAF50")
        self._log_text.tag_config("OUT", foreground="#64B5F6")
        self._log_text.tag_config("ERR", foreground=C["red"])
        self._log_text.tag_config("INF", foreground=C["dim"])

    # ─────────────────────────── MQTT ───────────────────────────

    def _toggle_connection(self):
        if self._connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        broker = self._broker_f.get().strip()
        try:
            port = int(self._port_f.get().strip())
        except ValueError:
            messagebox.showerror("Ошибка", "Неверный порт.")
            return

        self._log(f"Подключение к {broker}:{port} …", "INF")

        client_id = f"SmartGrowHub_{random.randint(10000, 99999)}"
        self._mqtt = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION1,
            client_id=client_id,
        )
        self._mqtt.on_connect    = self._on_connect
        self._mqtt.on_disconnect = self._on_disconnect
        self._mqtt.on_message    = self._on_message

        try:
            self._mqtt.connect_async(broker, port, keepalive=60)
            self._mqtt.loop_start()
        except Exception as exc:
            self._log(f"Ошибка: {exc}", "ERR")

    def _disconnect(self):
        if self._mqtt:
            self._mqtt.loop_stop()
            self._mqtt.disconnect()

    # ── MQTT callbacks (run on MQTT thread, schedule to main thread) ──

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            topic = self._topic_f.get().strip() + "/sensors/"
            client.subscribe(topic)
            self.after(0, self._ui_connected)
            self.after(0, lambda: self._log(f"Подключено. Подписка: {topic}", "INF"))
        else:
            codes = {1: "неверный протокол", 2: "отклонён ID клиента",
                     3: "сервер недоступен", 4: "неверные данные", 5: "не авторизован"}
            reason = codes.get(rc, f"rc={rc}")
            self.after(0, lambda: self._log(f"Ошибка подключения: {reason}", "ERR"))

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        self.after(0, self._ui_disconnected)
        msg = "Отключено." if rc == 0 else f"Соединение потеряно (rc={rc})."
        self.after(0, lambda: self._log(msg, "INF"))

    def _on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode("utf-8", errors="replace")
        except Exception:
            return

        self.after(0, lambda: self._log(f"← {payload}", "IN"))

        try:
            data = json.loads(payload)
            self.after(0, lambda d=data: self._update_sensors(d))
        except json.JSONDecodeError:
            pass

    # ── sensor update ──

    def _update_sensors(self, data: dict):
        for s in data.get("data", []):
            stype = s.get("Type")
            value = s.get("Value")
            if stype in self._sensor_cards and value is not None:
                self._sensor_cards[stype].update(value)
        now = datetime.now().strftime("%H:%M:%S")
        self._upd_lbl.config(text=f"Последнее обновление: {now}")

    # ── send command ──

    def send_command(self, module_type: str, mode: str,
                     action: str, schedule_unit: Optional[dict]):
        if not self._connected or self._mqtt is None:
            messagebox.showwarning("Нет подключения",
                                   "Сначала подключитесь к MQTT-брокеру.", parent=self)
            return

        device_id    = self._device_f.get().strip()
        topic_prefix = self._topic_f.get().strip()
        topic        = topic_prefix + "/modules/"

        payload = {
            "device_id":  device_id,
            "message_id": gen_ulid(),
            "mode":       mode,
            "action":     action,
            "type":       module_type,
            "schedule_unit": schedule_unit if schedule_unit is not None else {
                "kind": "", "schedule_unit_id": "",
                "interval": {}, "quantity": {},
            },
        }

        msg = json.dumps(payload, ensure_ascii=False)
        self._mqtt.publish(topic, msg)
        self._log(f"→ [{topic}] {msg}", "OUT")

    # ── UI state helpers ──

    def _ui_connected(self):
        self._connected = True
        self._dot_lbl.config(fg=C["accent"])
        self._status_lbl.config(text="Подключено", fg=C["accent"])
        self._conn_btn.config(text="Отключить", bg=C["red"],
                               activebackground="#c62828")

    def _ui_disconnected(self):
        self._dot_lbl.config(fg=C["red"])
        self._status_lbl.config(text="Отключено", fg=C["dim"])
        self._conn_btn.config(text="Подключить", bg=C["accent"],
                               activebackground="#388E3C")

    def _log(self, text: str, tag: str = "INF"):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_text.insert(tk.END, f"[{ts}] {text}\n", tag)
        self._log_text.see(tk.END)

    def _on_close(self):
        if self._mqtt:
            self._mqtt.loop_stop()
            try:
                self._mqtt.disconnect()
            except Exception:
                pass
        self.destroy()


# ─────────────────────────── Entry point ───────────────────────────

if __name__ == "__main__":
    app = SmartGrowHubApp()
    app.mainloop()
