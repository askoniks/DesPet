import os
import sys
import json
import random
import re
import shutil
import threading
import webbrowser
import zipfile
import winsound
import winreg
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox, ttk
from PIL import Image, ImageTk, ImageDraw
import pystray
from pystray import MenuItem as item

APP_NAME = "DesPet"
APP_VERSION = "1.1.0"
AUTOSTART_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
PET_IMAGE_NAME = "image.png"
PET_SOUNDS_DIR = "sounds"
# Ссылка «Поделиться петом» — меняйте в %APPDATA%\DesPet\config.json → "share_url"
DEFAULT_SHARE_URL = "http://144.31.158.222:8765/"
DEFAULT_PET_SIZE = 200
MIN_PET_SIZE = 50
MAX_PET_SIZE = 1000
INVALID_FOLDER_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_pet_name(name):
    name = (name or "").strip()
    name = INVALID_FOLDER_CHARS.sub("_", name)
    name = name.strip(". ")
    return name or "pet"


def find_pet_image(pet_folder):
    preferred = os.path.join(pet_folder, PET_IMAGE_NAME)
    if os.path.isfile(preferred):
        return preferred
    for entry in sorted(os.listdir(pet_folder)):
        path = os.path.join(pet_folder, entry)
        if os.path.isfile(path) and entry.lower().endswith(".png"):
            return path
    return None


def list_click_sounds(pet_folder):
    sounds_dir = os.path.join(pet_folder, PET_SOUNDS_DIR)
    if not os.path.isdir(sounds_dir):
        return []
    return [
        os.path.join(sounds_dir, f)
        for f in sorted(os.listdir(sounds_dir))
        if f.lower().endswith(".wav") and os.path.isfile(os.path.join(sounds_dir, f))
    ]


def open_in_explorer(path):
  os.startfile(os.path.normpath(path))


def autostart_is_enabled():
  try:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REG_KEY) as key:
      winreg.QueryValueEx(key, APP_NAME)
      return True
  except OSError:
    return False


def set_autostart(enabled):
  with winreg.OpenKey(
    winreg.HKEY_CURRENT_USER, AUTOSTART_REG_KEY, 0, winreg.KEY_SET_VALUE
  ) as key:
    if enabled:
      script = os.path.abspath(sys.argv[0])
      exe = sys.executable
      if exe.lower().endswith(("python.exe", "pythonw.exe")):
        command = f'"{exe}" "{script}"'
      else:
        command = f'"{exe}"'
      winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
    else:
      try:
        winreg.DeleteValue(key, APP_NAME)
      except FileNotFoundError:
        pass


def list_installed_pets(pets_dir):
    if not os.path.isdir(pets_dir):
        return []
    pets = []
    for name in sorted(os.listdir(pets_dir)):
        folder = os.path.join(pets_dir, name)
        if os.path.isdir(folder) and find_pet_image(folder):
            pets.append(name)
    return pets


class PetWindow:
  def __init__(self, app, pet_id):
    self.app = app
    self.pet_id = pet_id
    self.folder = os.path.join(app.pets_dir, pet_id)
    self.original_img = None
    self.tk_image = None
    self.drag_x = 0
    self.drag_y = 0
    self.is_dragging = False
    self._idle_after = None

    self.root = tk.Toplevel(app.root)
    self.root.overrideredirect(True)
    self.root.attributes("-topmost", True)
    self.root.config(bg="#010101")
    self.root.attributes("-transparentcolor", "#010101")

    self.canvas = tk.Canvas(self.root, bg="#010101", highlightthickness=0)
    self.canvas.pack(fill=tk.BOTH, expand=True)
    self.canvas.bind("<ButtonPress-1>", self.on_press)
    self.canvas.bind("<B1-Motion>", self.on_motion)
    self.canvas.bind("<ButtonRelease-1>", self.on_release)
    self.canvas.bind("<Button-3>", self.on_right_click)
    self._setup_context_menu()

    self.load_image()
    self.place_window()
    self.render_pet(1.0)
    self.start_idle_loop()

  def load_image(self):
    path = find_pet_image(self.folder)
    if not path:
      raise FileNotFoundError(f"No image in pet folder: {self.folder}")
    self.original_img = Image.open(path).convert("RGBA")

  def pet_size(self):
    return self.app.get_pet_size(self.pet_id)

  def place_window(self):
    size = self.pet_size()
    x, y = self.app.get_pet_position(self.pet_id)
    if x is None or y is None:
      sw = self.root.winfo_screenwidth()
      sh = self.root.winfo_screenheight()
      offset = len(self.app.active_pets) * 40
      x = (sw - size) // 2 + offset
      y = (sh - size) // 2 + offset
    self.root.geometry(f"{size}x{size}+{x}+{y}")

  def update_size(self):
    size = self.pet_size()
    x = self.root.winfo_x()
    y = self.root.winfo_y()
    self.root.geometry(f"{size}x{size}+{x}+{y}")
    self.render_pet(1.0)

  def save_position(self):
    self.app.save_pet_position(
      self.pet_id,
      self.root.winfo_x(),
      self.root.winfo_y(),
    )

  def render_pet(self, scale_factor=1.0):
    if not self.original_img:
      return
    size = self.pet_size()
    target_size = int(size * scale_factor)
    img_w, img_h = self.original_img.size
    ratio = min(target_size / img_w, target_size / img_h)
    new_w = max(1, int(img_w * ratio))
    new_h = max(1, int(img_h * ratio))
    resized = self.original_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    self.tk_image = ImageTk.PhotoImage(resized)
    self.canvas.delete("all")
    self.canvas.create_image(
      size // 2,
      size // 2,
      image=self.tk_image,
      anchor=tk.CENTER,
    )

  def _setup_context_menu(self):
    self._ctx = tk.Menu(self.root, tearoff=0)
    self._ctx.add_command(
      label=self.app.t("ctx_hide"),
      command=lambda: self.app.safe_ui_call(self.app.hide_pet, self.pet_id),
    )
    self._ctx.add_command(
      label=self.app.t("ctx_size"),
      command=lambda: self.app.safe_ui_call(self.app.ask_pet_size, self.pet_id),
    )
    self._ctx.add_command(
      label=self.app.t("ctx_reset_pos"),
      command=lambda: self.app.safe_ui_call(self.app.reset_pet_position, self.pet_id),
    )

  def on_right_click(self, event):
    self._cancel_idle()
    try:
      self._ctx.tk_popup(event.x_root, event.y_root)
    finally:
      self._ctx.grab_release()

  def _cancel_idle(self):
    if self._idle_after is not None:
      self.root.after_cancel(self._idle_after)
      self._idle_after = None

  def start_idle_loop(self):
    self._cancel_idle()
    if self.app.config.get("idle_animation", True):
      self._schedule_idle()

  def _schedule_idle(self):
    if not self.root.winfo_exists():
      return
    delay = random.randint(4500, 9500)
    self._idle_after = self.root.after(delay, self._idle_tick)

  def _idle_tick(self):
    self._idle_after = None
    if self.is_dragging or self.pet_id not in self.app.active_pets:
      return
    if not self.app.config.get("idle_animation", True):
      return
    self.render_pet(1.06)
    self.root.after(130, lambda: self.render_pet(1.0))
    self._schedule_idle()

  def on_press(self, event):
    self._cancel_idle()
    self.drag_x = event.x
    self.drag_y = event.y
    self.is_dragging = False

  def on_motion(self, event):
    dx = event.x - self.drag_x
    dy = event.y - self.drag_y
    if abs(dx) > 3 or abs(dy) > 3:
      self.is_dragging = True
    x = self.root.winfo_x() + dx
    y = self.root.winfo_y() + dy
    self.root.geometry(f"+{x}+{y}")

  def on_release(self, event):
    if self.is_dragging:
      self.save_position()
    else:
      self.play_random_sound()
      self.animate_click()
    self.start_idle_loop()

  def play_random_sound(self):
    if not self.app.config.get("sound_enabled"):
      return
    sounds = list_click_sounds(self.folder)
    if not sounds:
      return
    path = random.choice(sounds)
    winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)

  def animate_click(self):
    self.render_pet(0.9)
    self.root.after(100, lambda: self.render_pet(1.0))

  def destroy(self):
    self._cancel_idle()
    self.save_position()
    self.root.destroy()


class CreatePetDialog(tk.Toplevel):
  def __init__(self, app):
    super().__init__()
    self.app = app
    self.result = None
    self.image_path = ""
    self.sound_paths = []

    self.title(app.t("create_pet_title"))
    self.resizable(False, False)
    self.protocol("WM_DELETE_WINDOW", self.on_cancel)

    pad = {"padx": 10, "pady": 5}
    ttk.Label(self, text=app.t("pet_name")).grid(row=0, column=0, sticky="w", **pad)
    self.name_var = tk.StringVar()
    ttk.Entry(self, textvariable=self.name_var, width=48).grid(
      row=0, column=1, columnspan=2, sticky="ew", **pad
    )

    ttk.Label(self, text=app.t("pet_image")).grid(row=1, column=0, sticky="w", **pad)
    self.image_var = tk.StringVar(value=app.t("not_selected"))
    ttk.Entry(self, textvariable=self.image_var, width=40, state="readonly").grid(
      row=1, column=1, sticky="ew", **pad
    )
    ttk.Button(self, text=app.t("browse_image"), command=self.pick_image).grid(row=1, column=2, **pad)

    ttk.Label(self, text=app.t("pet_sounds")).grid(row=2, column=0, sticky="nw", **pad)
    sounds_frame = ttk.Frame(self)
    sounds_frame.grid(row=2, column=1, columnspan=2, sticky="nsew", **pad)
    self.sounds_list = tk.Listbox(sounds_frame, height=5, width=52)
    self.sounds_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scroll = ttk.Scrollbar(sounds_frame, orient=tk.VERTICAL, command=self.sounds_list.yview)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)
    self.sounds_list.config(yscrollcommand=scroll.set)

    sound_btns = ttk.Frame(self)
    sound_btns.grid(row=3, column=1, columnspan=2, sticky="w", **pad)
    ttk.Button(sound_btns, text=app.t("add_sounds"), command=self.pick_sounds).pack(
      side=tk.LEFT, padx=(0, 6)
    )
    ttk.Button(sound_btns, text=app.t("remove_sound"), command=self.remove_sound).pack(side=tk.LEFT)

    btn_frame = ttk.Frame(self)
    btn_frame.grid(row=4, column=0, columnspan=3, pady=14)
    ttk.Button(btn_frame, text=app.t("create"), command=self.on_create).pack(side=tk.LEFT, padx=8)
    ttk.Button(btn_frame, text=app.t("cancel"), command=self.on_cancel).pack(side=tk.LEFT, padx=8)

    self.columnconfigure(1, weight=1)
    self._center_on_screen()

  def _center_on_screen(self):
    self.update_idletasks()
    w = self.winfo_reqwidth()
    h = self.winfo_reqheight()
    sw = self.winfo_screenwidth()
    sh = self.winfo_screenheight()
    self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
    self.deiconify()
    self.lift()
    self.attributes("-topmost", True)
    self.after(200, lambda: self.attributes("-topmost", False))
    self.focus_force()

  def pick_image(self):
    path = filedialog.askopenfilename(
      parent=self,
      title=self.app.t("pick_image_title"),
      filetypes=[
        (self.app.t("png_files"), "*.png"),
        (self.app.t("all_files"), "*.*"),
      ],
    )
    if path:
      self.image_path = path
      self.image_var.set(path)

  def pick_sounds(self):
    paths = filedialog.askopenfilenames(
      parent=self,
      title=self.app.t("pick_sounds_title"),
      filetypes=[
        (self.app.t("wav_files"), "*.wav"),
        (self.app.t("all_files"), "*.*"),
      ],
    )
    for path in paths:
      if path and path not in self.sound_paths:
        self.sound_paths.append(path)
        self.sounds_list.insert(tk.END, path)

  def remove_sound(self):
    sel = self.sounds_list.curselection()
    if not sel:
      return
    idx = sel[0]
    self.sounds_list.delete(idx)
    del self.sound_paths[idx]

  def on_cancel(self):
    self.result = None
    self.destroy()

  def on_create(self):
    name = sanitize_pet_name(self.name_var.get())
    if not name:
      messagebox.showerror(self.app.t("error"), self.app.t("name_required"), parent=self)
      return
    if not self.image_path or not os.path.isfile(self.image_path):
      messagebox.showerror(self.app.t("error"), self.app.t("image_required"), parent=self)
      return
    dest = os.path.join(self.app.pets_dir, name)
    if os.path.exists(dest):
      messagebox.showerror(self.app.t("error"), self.app.t("pet_exists"), parent=self)
      return
    self.result = {"name": name, "image": self.image_path, "sounds": list(self.sound_paths)}
    self.destroy()


class DesPetApp:
  def __init__(self):
    self.app_name = APP_NAME
    self.appdata_dir = os.path.join(os.environ.get("APPDATA", ""), self.app_name)
    self.pets_dir = os.path.join(self.appdata_dir, "pets")
    self.config_file = os.path.join(self.appdata_dir, "config.json")

    self.default_config = {
      "lang": "ru",
      "sound_enabled": True,
      "share_url": DEFAULT_SHARE_URL,
      "default_pet_size": DEFAULT_PET_SIZE,
      "idle_animation": True,
      "autostart": False,
      "pets": {
        "default": {
          "enabled": True,
          "size": DEFAULT_PET_SIZE,
          "x": None,
          "y": None,
        }
      },
    }
    self.langs = {
      "ru": {
        "made_by": f"DesPet v{APP_VERSION}",
        "tray_title": "{app} v{version} — на экране: {active}/{total}",
        "about_text": "DesPet v{version}\n\nНастольные питомцы на рабочем столе.\nДанные: %APPDATA%\\DesPet\n\nПКМ по питомцу — быстрые действия.",
        "sound_on": "Звук: Вкл",
        "sound_off": "Звук: Выкл",
        "change_pet_size": "Изменить размер",
        "size_prompt_pet": "Размер «{name}» (50-1000):",
        "pets_menu": "Питомцы",
        "create_pet": "Создать питомца…",
        "import_pet": "Импорт питомца (.pet)",
        "language": "Язык / Language",
        "github": "Открыть Github",
        "exit": "Выход",
        "error": "Ошибка",
        "success": "Успешно",
        "import_ok": "Питомец «{name}» импортирован",
        "import_fail": "Не удалось импортировать: {err}",
        "create_pet_title": "Новый питомец",
        "pet_name": "Название:",
        "pet_image": "Картинка (PNG):",
        "pet_sounds": "Звуки клика (WAV):",
        "browse_image": "Выбрать картинку…",
        "pick_image_title": "Путь к картинке питомца",
        "pick_sounds_title": "Пути к звукам клика",
        "add_sounds": "Добавить звуки…",
        "pet_show": "Показать на экране",
        "export_pet": "Экспортировать как .pet…",
        "export_ok": "Пакет сохранён: {path}",
        "export_fail": "Не удалось экспортировать: {err}",
        "delete_pet": "Удалить питомца",
        "delete_confirm": "Удалить питомца «{name}» безвозвратно?",
        "delete_ok": "Питомец «{name}» удалён",
        "share_pet": "Поделиться петом",
        "share_url_empty": "Укажите ссылку в config.json (поле share_url)",
        "remove_sound": "Убрать",
        "create": "Создать",
        "cancel": "Отмена",
        "not_selected": "не выбрано",
        "name_required": "Введите название питомца",
        "image_required": "Выберите картинку",
        "pet_exists": "Питомец с таким именем уже есть",
        "png_files": "PNG",
        "wav_files": "WAV",
        "all_files": "Все файлы",
        "pet_created": "Питомец «{name}» создан",
        "no_pets": "Нет питомцев",
        "show_all": "Показать всех",
        "hide_all": "Скрыть всех",
        "reset_position": "Сбросить позицию",
        "open_pets_folder": "Открыть папку питомцев",
        "open_data_folder": "Открыть папку данных",
        "idle_anim": "Анимация покоя",
        "autostart": "Запуск с Windows",
        "about": "О программе",
        "ctx_hide": "Скрыть",
        "ctx_size": "Изменить размер…",
        "ctx_reset_pos": "Сбросить позицию",
      },
      "en": {
        "made_by": f"DesPet v{APP_VERSION}",
        "tray_title": "{app} v{version} — on screen: {active}/{total}",
        "about_text": "DesPet v{version}\n\nDesktop pets for Windows.\nData: %APPDATA%\\DesPet\n\nRight-click a pet for quick actions.",
        "sound_on": "Sound: On",
        "sound_off": "Sound: Off",
        "change_pet_size": "Change size",
        "size_prompt_pet": "Size of «{name}» (50-1000):",
        "pets_menu": "Pets",
        "create_pet": "Create pet…",
        "import_pet": "Import pet (.pet)",
        "language": "Language / Язык",
        "github": "Open Github",
        "exit": "Exit",
        "error": "Error",
        "success": "Success",
        "import_ok": "Pet «{name}» imported",
        "import_fail": "Import failed: {err}",
        "create_pet_title": "New pet",
        "pet_name": "Name:",
        "pet_image": "Image (PNG):",
        "pet_sounds": "Click sounds (WAV):",
        "browse_image": "Choose image…",
        "pick_image_title": "Pet image path",
        "pick_sounds_title": "Click sound paths",
        "add_sounds": "Add sounds…",
        "pet_show": "Show on screen",
        "export_pet": "Export as .pet…",
        "export_ok": "Pack saved: {path}",
        "export_fail": "Export failed: {err}",
        "delete_pet": "Delete pet",
        "delete_confirm": "Permanently delete pet «{name}»?",
        "delete_ok": "Pet «{name}» deleted",
        "share_pet": "Share pet",
        "share_url_empty": "Set share_url in config.json",
        "remove_sound": "Remove",
        "create": "Create",
        "cancel": "Cancel",
        "not_selected": "not selected",
        "name_required": "Enter a pet name",
        "image_required": "Select an image",
        "pet_exists": "A pet with this name already exists",
        "png_files": "PNG",
        "wav_files": "WAV",
        "all_files": "All files",
        "pet_created": "Pet «{name}» created",
        "no_pets": "No pets",
        "show_all": "Show all",
        "hide_all": "Hide all",
        "reset_position": "Reset position",
        "open_pets_folder": "Open pets folder",
        "open_data_folder": "Open data folder",
        "idle_anim": "Idle animation",
        "autostart": "Run at Windows startup",
        "about": "About",
        "ctx_hide": "Hide",
        "ctx_size": "Change size…",
        "ctx_reset_pos": "Reset position",
      },
    }

    self.setup_appdata()
    self.config = self.load_config()
    self._sync_autostart_from_registry()
    self.active_pets = {}
    self.tray_icon = None
    self._create_dialog = None

    self.root = tk.Tk()
    self.root.withdraw()

    self.spawn_active_pets()
    threading.Thread(target=self.run_tray, daemon=True).start()
    self.root.after(500, self.update_tray_title)
    self.root.mainloop()

  def t(self, key):
    return self.langs.get(self.config.get("lang", "ru"), self.langs["en"]).get(key, key)

  def setup_appdata(self):
    os.makedirs(self.pets_dir, exist_ok=True)
    default_folder = os.path.join(self.pets_dir, "default")
    default_image = os.path.join(default_folder, PET_IMAGE_NAME)
    if not os.path.isfile(default_image):
      os.makedirs(os.path.join(default_folder, PET_SOUNDS_DIR), exist_ok=True)
      img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
      draw = ImageDraw.Draw(img)
      draw.ellipse((20, 20, 180, 180), fill=(100, 150, 255, 255))
      draw.ellipse((60, 60, 80, 80), fill=(255, 255, 255, 255))
      draw.ellipse((120, 60, 140, 80), fill=(255, 255, 255, 255))
      draw.arc((60, 100, 140, 150), start=0, end=180, fill=(255, 255, 255, 255), width=10)
      img.save(default_image)

  def load_config(self):
    if os.path.exists(self.config_file):
      try:
        with open(self.config_file, "r", encoding="utf-8") as f:
          data = json.load(f)
        cfg = {**self.default_config, **data}
        return self._migrate_config(cfg)
      except (json.JSONDecodeError, OSError):
        pass
    return self._migrate_config(self.default_config.copy())

  def _migrate_config(self, cfg):
    """Старый формат: size, active_pets, pet_positions → pets.{id}.{enabled,size,x,y}."""
    pets = cfg.setdefault("pets", {})
    if not isinstance(pets, dict):
      pets = {}
      cfg["pets"] = pets

    fallback_size = cfg.pop("size", None) or cfg.get("default_pet_size", DEFAULT_PET_SIZE)
    cfg.setdefault("default_pet_size", fallback_size)

    for pet_id in cfg.pop("active_pets", []) or []:
      entry = pets.setdefault(pet_id, {})
      entry["enabled"] = True
      entry.setdefault("size", fallback_size)

    for pet_id, pos in (cfg.pop("pet_positions", None) or {}).items():
      entry = pets.setdefault(pet_id, {})
      if isinstance(pos, dict):
        if "x" in pos:
          entry["x"] = pos["x"]
        if "y" in pos:
          entry["y"] = pos["y"]
      entry.setdefault("size", fallback_size)

    for pet_id, entry in list(pets.items()):
      if not isinstance(entry, dict):
        pets[pet_id] = {"enabled": False, "size": fallback_size, "x": None, "y": None}
        continue
      if isinstance(entry.get("position"), dict):
        pos = entry.pop("position")
        entry.setdefault("x", pos.get("x"))
        entry.setdefault("y", pos.get("y"))
      entry.setdefault("enabled", False)
      entry.setdefault("size", fallback_size)
      entry.setdefault("x", None)
      entry.setdefault("y", None)

    if "default" not in pets and os.path.isdir(os.path.join(self.pets_dir, "default")):
      pets["default"] = {
        "enabled": True,
        "size": fallback_size,
        "x": None,
        "y": None,
      }

    cfg.setdefault("idle_animation", True)
    cfg.setdefault("autostart", autostart_is_enabled())
    return cfg

  def _sync_autostart_from_registry(self):
    reg = autostart_is_enabled()
    if self.config.get("autostart") and not reg:
      set_autostart(True)
    elif not self.config.get("autostart") and reg:
      set_autostart(False)

  def save_config(self):
    self._sync_pets_settings_to_disk()
    with open(self.config_file, "w", encoding="utf-8") as f:
      json.dump(self.config, f, indent=4, ensure_ascii=False)

  def _sync_pets_settings_to_disk(self):
    """Записать в config всех установленных питомцев (без лишних удалённых папок)."""
    installed = set(list_installed_pets(self.pets_dir))
    pets = self.config.setdefault("pets", {})
    for pet_id in installed:
      self.ensure_pet_settings(pet_id)
    for pet_id in list(pets.keys()):
      if pet_id not in installed:
        del pets[pet_id]

  def ensure_pet_settings(self, pet_id):
    pets = self.config.setdefault("pets", {})
    if pet_id not in pets or not isinstance(pets[pet_id], dict):
      pets[pet_id] = {
        "enabled": pet_id == "default",
        "size": self.config.get("default_pet_size", DEFAULT_PET_SIZE),
        "x": None,
        "y": None,
      }
    entry = pets[pet_id]
    entry.setdefault("enabled", False)
    entry.setdefault("size", self.config.get("default_pet_size", DEFAULT_PET_SIZE))
    entry.setdefault("x", None)
    entry.setdefault("y", None)
    return entry

  def get_pet_settings(self, pet_id):
    return self.ensure_pet_settings(pet_id)

  def is_pet_enabled(self, pet_id):
    return bool(self.get_pet_settings(pet_id).get("enabled"))

  def set_pet_enabled(self, pet_id, enabled, persist=True):
    self.get_pet_settings(pet_id)["enabled"] = bool(enabled)
    if persist:
      self.save_config()

  def get_pet_size(self, pet_id):
    return int(self.get_pet_settings(pet_id).get("size", DEFAULT_PET_SIZE))

  def set_pet_size(self, pet_id, size):
    self.get_pet_settings(pet_id)["size"] = max(MIN_PET_SIZE, min(MAX_PET_SIZE, int(size)))
    self.save_config()

  def get_pet_position(self, pet_id):
    entry = self.get_pet_settings(pet_id)
    x, y = entry.get("x"), entry.get("y")
    if x is not None and y is not None:
      return int(x), int(y)
    return None, None

  def save_pet_position(self, pet_id, x, y):
    entry = self.get_pet_settings(pet_id)
    entry["x"] = int(x)
    entry["y"] = int(y)
    self.save_config()

  def init_new_pet_settings(self, pet_id, enabled=True):
    default_size = self.config.get("default_pet_size", DEFAULT_PET_SIZE)
    self.config.setdefault("pets", {})[pet_id] = {
      "enabled": enabled,
      "size": default_size,
      "x": None,
      "y": None,
    }
    self.save_config()

  def safe_ui_call(self, func, *args):
    self.root.after(0, lambda: func(*args))

  def spawn_active_pets(self):
    installed = list_installed_pets(self.pets_dir)
    if not installed:
      return
    enabled_any = False
    for pet_id in installed:
      self.ensure_pet_settings(pet_id)
      if self.is_pet_enabled(pet_id):
        enabled_any = True
        self.show_pet(pet_id, save_config=False)
    if not enabled_any and "default" in installed:
      self.get_pet_settings("default")["enabled"] = True
      self.show_pet("default", save_config=False)
    self.save_config()
    self.root.after(100, self.update_tray_title)

  def show_pet(self, pet_id, save_config=True):
    if pet_id in self.active_pets:
      return
    folder = os.path.join(self.pets_dir, pet_id)
    if not os.path.isdir(folder) or not find_pet_image(folder):
      return
    try:
      self.active_pets[pet_id] = PetWindow(self, pet_id)
    except OSError as e:
      messagebox.showerror(self.t("error"), str(e))
      return
    self.set_pet_enabled(pet_id, True, persist=save_config)
    self.update_tray_title()

  def hide_pet(self, pet_id, save_config=True):
    window = self.active_pets.pop(pet_id, None)
    if window:
      window.destroy()
    if save_config:
      self.set_pet_enabled(pet_id, False, persist=True)
    self.update_tray_title()

  def hide_pet_runtime_only(self, pet_id):
    """Закрыть окно при выходе, enabled в конфиге не менять."""
    window = self.active_pets.pop(pet_id, None)
    if window:
      window.save_position()
      window.root.destroy()

  def toggle_pet(self, pet_id):
    if pet_id in self.active_pets:
      self.hide_pet(pet_id)
    else:
      self.show_pet(pet_id)

  def show_all_pets(self):
    for pet_id in list_installed_pets(self.pets_dir):
      self.show_pet(pet_id, save_config=False)
    self.save_config()
    self.update_tray_title()

  def hide_all_pets(self):
    for pet_id in list(self.active_pets.keys()):
      self.hide_pet(pet_id, save_config=False)
    self.save_config()
    self.update_tray_title()

  def reset_pet_position(self, pet_id):
    entry = self.get_pet_settings(pet_id)
    entry["x"] = None
    entry["y"] = None
    self.save_config()
    if pet_id in self.active_pets:
      win = self.active_pets[pet_id]
      win.place_window()
      win.render_pet(1.0)

  def open_pets_folder(self):
    open_in_explorer(self.pets_dir)

  def open_data_folder(self):
    open_in_explorer(self.appdata_dir)

  def toggle_idle_animation(self):
    self.config["idle_animation"] = not self.config.get("idle_animation", True)
    self.save_config()
    if self.config["idle_animation"]:
      for pet in self.active_pets.values():
        pet.start_idle_loop()
    else:
      for pet in self.active_pets.values():
        pet._cancel_idle()

  def toggle_autostart(self):
    enabled = not self.config.get("autostart", False)
    self.config["autostart"] = enabled
    set_autostart(enabled)
    self.save_config()

  def show_about(self):
    messagebox.showinfo(
      self.app_name,
      self.t("about_text").format(version=APP_VERSION),
    )

  def update_tray_title(self):
    if not self.tray_icon:
      return
    total = len(list_installed_pets(self.pets_dir))
    active = len(self.active_pets)
    self.tray_icon.title = self.t("tray_title").format(
      app=APP_NAME,
      version=APP_VERSION,
      active=active,
      total=total,
    )

  def create_pet_from_dialog(self):
    if getattr(self, "_create_dialog", None):
      try:
        if self._create_dialog.winfo_exists():
          self._create_dialog.lift()
          self._create_dialog.focus_force()
          return
      except tk.TclError:
        pass

    dialog = CreatePetDialog(self)
    self._create_dialog = dialog
    self.root.wait_window(dialog)
    self._create_dialog = None
    if not dialog.result:
      return

    data = dialog.result
    name = data["name"]
    dest = os.path.join(self.pets_dir, name)
    sounds_dir = os.path.join(dest, PET_SOUNDS_DIR)
    try:
      os.makedirs(sounds_dir, exist_ok=True)
      shutil.copy2(data["image"], os.path.join(dest, PET_IMAGE_NAME))
      for src in data["sounds"]:
        shutil.copy2(src, os.path.join(sounds_dir, os.path.basename(src)))
    except OSError as e:
      messagebox.showerror(self.t("error"), str(e), parent=self.root)
      if os.path.isdir(dest):
        shutil.rmtree(dest, ignore_errors=True)
      return
    self.init_new_pet_settings(name, enabled=True)
    messagebox.showinfo(self.t("success"), self.t("pet_created").format(name=name), parent=self.root)
    self.show_pet(name, save_config=False)
    self.save_config()

  def export_pet_pack(self, pet_id):
    folder = os.path.join(self.pets_dir, pet_id)
    if not os.path.isdir(folder):
      messagebox.showerror(self.t("error"), self.t("export_fail").format(err="pet not found"), parent=self.root)
      return

    path = filedialog.asksaveasfilename(
      title=self.t("export_pet"),
      defaultextension=".pet",
      initialfile=f"{pet_id}.pet",
      filetypes=[(self.t("import_pet"), "*.pet"), (self.t("all_files"), "*.*")],
    )
    if not path:
      return
    if not path.lower().endswith(".pet"):
      path += ".pet"

    try:
      with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root_dir, _, files in os.walk(folder):
          for fname in files:
            full_path = os.path.join(root_dir, fname)
            arcname = os.path.join(pet_id, os.path.relpath(full_path, folder)).replace("\\", "/")
            zf.write(full_path, arcname)
      messagebox.showinfo(self.t("success"), self.t("export_ok").format(path=path), parent=self.root)
    except OSError as e:
      messagebox.showerror(self.t("error"), self.t("export_fail").format(err=e), parent=self.root)

  def confirm_delete_pet(self, pet_id):
    if not messagebox.askyesno(
      self.app_name,
      self.t("delete_confirm").format(name=pet_id),
    ):
      return
    self.delete_pet(pet_id)

  def delete_pet(self, pet_id):
    self.hide_pet(pet_id, save_config=False)
    folder = os.path.join(self.pets_dir, pet_id)
    if os.path.isdir(folder):
      try:
        shutil.rmtree(folder)
      except OSError as e:
        messagebox.showerror(self.t("error"), str(e))
        return
    pets = self.config.get("pets", {})
    pets.pop(pet_id, None)
    self.save_config()
    if not list_installed_pets(self.pets_dir):
      self.setup_appdata()
    messagebox.showinfo(self.t("success"), self.t("delete_ok").format(name=pet_id))

  def open_share_link(self):
    url = (self.config.get("share_url") or DEFAULT_SHARE_URL).strip()
    if not url:
      messagebox.showwarning(self.app_name, self.t("share_url_empty"))
      return
    webbrowser.open(url)

  def import_pet_pack(self):
    path = filedialog.askopenfilename(
      title=self.t("import_pet"),
      filetypes=[(self.t("import_pet"), "*.pet"), (self.t("all_files"), "*.*")],
    )
    if not path:
      return
    try:
      name = self._install_pet_archive(path)
      self.init_new_pet_settings(name, enabled=True)
      messagebox.showinfo(self.t("success"), self.t("import_ok").format(name=name))
      self.show_pet(name, save_config=False)
      self.save_config()
    except Exception as e:
      messagebox.showerror(self.t("error"), self.t("import_fail").format(err=e))

  def _install_pet_archive(self, archive_path):
    with zipfile.ZipFile(archive_path, "r") as zf:
      names = [n.replace("\\", "/") for n in zf.namelist() if not n.endswith("/")]
      if not names:
        raise ValueError("empty archive")

      top_levels = {n.split("/")[0] for n in names}
      if len(top_levels) == 1 and any("/" in n for n in names):
        root = next(iter(top_levels))
        prefix = root + "/"
      else:
        root = sanitize_pet_name(os.path.splitext(os.path.basename(archive_path))[0])
        prefix = ""

      dest = os.path.join(self.pets_dir, root)
      if os.path.exists(dest):
        raise ValueError(f"pet folder already exists: {root}")

      os.makedirs(dest, exist_ok=True)
      try:
        for member in zf.namelist():
          norm = member.replace("\\", "/")
          if norm.endswith("/"):
            continue
          rel = norm[len(prefix) :] if prefix and norm.startswith(prefix) else norm
          if not rel or rel.startswith("/"):
            continue
          target = os.path.join(dest, rel)
          os.makedirs(os.path.dirname(target), exist_ok=True)
          with zf.open(member) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)
      except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise

    if not find_pet_image(dest):
      shutil.rmtree(dest, ignore_errors=True)
      raise ValueError("no image.png or PNG in pet root")
    os.makedirs(os.path.join(dest, PET_SOUNDS_DIR), exist_ok=True)
    return root

  def create_tray_image(self):
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
    if os.path.isfile(icon_path):
      return Image.open(icon_path)
    img = Image.new("RGB", (64, 64), color=(30, 30, 30))
    draw = ImageDraw.Draw(img)
    draw.ellipse((16, 16, 48, 48), fill=(200, 200, 200))
    return img

  def run_tray(self):
    # Динамическое меню: собирается при каждом открытии, без пересоздания после клика —
    # иначе на Windows подменю сразу закрывается.
    self.tray_icon = pystray.Icon(
      self.app_name,
      self.create_tray_image(),
      self.app_name,
      menu=pystray.Menu(self._build_tray_menu),
    )
    self.update_tray_title()
    self.tray_icon.run()

  def _build_tray_menu(self, _menu=None):
    installed = list_installed_pets(self.pets_dir)

    def make_show_toggle(pid):
      return lambda icon, item: self.safe_ui_call(self.toggle_pet, pid)

    def make_export(pid):
      return lambda icon, item: self.safe_ui_call(self.export_pet_pack, pid)

    def make_delete(pid):
      return lambda icon, item: self.safe_ui_call(self.confirm_delete_pet, pid)

    def make_size(pid):
      return lambda icon, item: self.safe_ui_call(self.ask_pet_size, pid)

    def make_reset_pos(pid):
      return lambda icon, item: self.safe_ui_call(self.reset_pet_position, pid)

    if installed:
      for pid in installed:
        self.ensure_pet_settings(pid)
      pet_items = [
        item(
          pid,
          pystray.Menu(
            item(
              self.t("pet_show"),
              make_show_toggle(pid),
              checked=lambda i, pid=pid: self.is_pet_enabled(pid),
            ),
            item(self.t("change_pet_size"), make_size(pid)),
            item(self.t("reset_position"), make_reset_pos(pid)),
            item(self.t("export_pet"), make_export(pid)),
            pystray.Menu.SEPARATOR,
            item(self.t("delete_pet"), make_delete(pid)),
          ),
        )
        for pid in installed
      ]
    else:
      pet_items = [item(self.t("no_pets"), None, enabled=False)]

    return (
      item(self.t("made_by"), None, enabled=False),
      pystray.Menu.SEPARATOR,
      item(
        self.t("sound_on") if self.config.get("sound_enabled") else self.t("sound_off"),
        lambda icon, item: self.safe_ui_call(self.toggle_sound),
      ),
      item(
        self.t("pets_menu"),
        pystray.Menu(
          *pet_items,
          pystray.Menu.SEPARATOR,
          item(self.t("show_all"), lambda icon, item: self.safe_ui_call(self.show_all_pets)),
          item(self.t("hide_all"), lambda icon, item: self.safe_ui_call(self.hide_all_pets)),
          item(self.t("create_pet"), lambda icon, item: self.safe_ui_call(self.create_pet_from_dialog)),
        ),
      ),
      item(self.t("import_pet"), lambda icon, item: self.safe_ui_call(self.import_pet_pack)),
      item(self.t("share_pet"), lambda icon, item: self.safe_ui_call(self.open_share_link)),
      pystray.Menu.SEPARATOR,
      item(
        self.t("open_pets_folder"),
        lambda icon, item: self.safe_ui_call(self.open_pets_folder),
      ),
      item(
        self.t("open_data_folder"),
        lambda icon, item: self.safe_ui_call(self.open_data_folder),
      ),
      item(
        self.t("idle_anim"),
        lambda icon, item: self.safe_ui_call(self.toggle_idle_animation),
        checked=lambda i: self.config.get("idle_animation", True),
      ),
      item(
        self.t("autostart"),
        lambda icon, item: self.safe_ui_call(self.toggle_autostart),
        checked=lambda i: self.config.get("autostart", False),
      ),
      pystray.Menu.SEPARATOR,
      item(
        self.t("language"),
        pystray.Menu(
          item("Русский", lambda icon, item: self.safe_ui_call(self.set_lang, "ru"), checked=lambda i: self.config["lang"] == "ru"),
          item("English", lambda icon, item: self.safe_ui_call(self.set_lang, "en"), checked=lambda i: self.config["lang"] == "en"),
        ),
      ),
      item(self.t("github"), lambda icon, item: webbrowser.open("https://github.com/kupitonov/DesPet")),
      item(self.t("about"), lambda icon, item: self.safe_ui_call(self.show_about)),
      pystray.Menu.SEPARATOR,
      item(self.t("exit"), lambda icon, item: self.safe_ui_call(self.exit_app)),
    )

  def toggle_sound(self):
    self.config["sound_enabled"] = not self.config.get("sound_enabled", True)
    self.save_config()

  def set_lang(self, lang):
    self.config["lang"] = lang
    self.save_config()

  def ask_pet_size(self, pet_id):
    new_size = simpledialog.askinteger(
      self.app_name,
      self.t("size_prompt_pet").format(name=pet_id),
      initialvalue=self.get_pet_size(pet_id),
      minvalue=MIN_PET_SIZE,
      maxvalue=MAX_PET_SIZE,
    )
    if not new_size:
      return
    self.set_pet_size(pet_id, new_size)
    if pet_id in self.active_pets:
      self.active_pets[pet_id].update_size()

  def exit_app(self):
    for pet_id in list(self.active_pets.keys()):
      self.hide_pet_runtime_only(pet_id)
    self.save_config()
    if self.tray_icon:
      self.tray_icon.stop()
    self.root.quit()


if __name__ == "__main__":
  DesPetApp()
