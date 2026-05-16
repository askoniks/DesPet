import os
import sys
import json
import shutil
import threading
import webbrowser
import winsound
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
from PIL import Image, ImageTk, ImageDraw
import pystray
from pystray import MenuItem as item

class TynnPetApp:
    def __init__(self):
        self.app_name = "TynnPet"
        self.appdata_dir = os.path.join(os.environ.get('APPDATA', ''), self.app_name)
        self.pets_dir = os.path.join(self.appdata_dir, "pets")
        self.sounds_dir = os.path.join(self.appdata_dir, "sounds")
        self.config_file = os.path.join(self.appdata_dir, "config.json")
        
        self.setup_appdata()
        
        self.default_config = {
            "size": 200,
            "lang": "ru",
            "sound_enabled": False,
            "selected_pet": "default.png",
            "selected_sound": ""
        }
        self.config = self.load_config()
        
        self.langs = {
            'ru': {
                'made_by': 'Сделано Tynn',
                'sound_on': 'Звук: Вкл',
                'sound_off': 'Звук: Выкл',
                'change_size': 'Изменить размер',
                'import_pet': 'Импорт питомца (PNG)',
                'import_sound': 'Импорт звука (WAV)',
                'select_pet': 'Выбрать питомца',
                'select_sound': 'Выбрать звук',
                'language': 'Язык / Language',
                'github': 'Открыть Github',
                'exit': 'Выход',
                'size_prompt': 'Введите размер (50-1000):',
                'no_sounds': 'Нет звуков',
                'none': 'Ничего',
                'error': 'Ошибка',
                'success': 'Успешно'
            },
            'en': {
                'made_by': 'Made by Tynn',
                'sound_on': 'Sound: On',
                'sound_off': 'Sound: Off',
                'change_size': 'Change size',
                'import_pet': 'Import pet (PNG)',
                'import_sound': 'Import sound (WAV)',
                'select_pet': 'Select pet',
                'select_sound': 'Select sound',
                'language': 'Language / Язык',
                'github': 'Open Github',
                'exit': 'Exit',
                'size_prompt': 'Enter size (50-1000):',
                'no_sounds': 'No sounds',
                'none': 'None',
                'error': 'Error',
                'success': 'Success'
            }
        }
        
        self.drag_x = 0
        self.drag_y = 0
        self.is_dragging = False
        self.tray_icon = None
        self.original_img = None
        self.tk_image = None
        
        self.root = tk.Tk()
        self.setup_window()
        self.load_pet()
        self.update_tray_menu()
        
        threading.Thread(target=self.run_tray, daemon=True).start()
        self.root.mainloop()

    def t(self, key):
        return self.langs.get(self.config['lang'], self.langs['en']).get(key, key)

    def setup_appdata(self):
        os.makedirs(self.pets_dir, exist_ok=True)
        os.makedirs(self.sounds_dir, exist_ok=True)
        
        default_pet_path = os.path.join(self.pets_dir, "default.png")
        if not os.listdir(self.pets_dir):
            img = Image.new('RGBA', (200, 200), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.ellipse((20, 20, 180, 180), fill=(100, 150, 255, 255))
            draw.ellipse((60, 60, 80, 80), fill=(255, 255, 255, 255))
            draw.ellipse((120, 60, 140, 80), fill=(255, 255, 255, 255))
            draw.arc((60, 100, 140, 150), start=0, end=180, fill=(255, 255, 255, 255), width=10)
            img.save(default_pet_path)

    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return {**self.default_config, **json.load(f)}
            except:
                pass
        return self.default_config.copy()

    def save_config(self):
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=4)

    def setup_window(self):
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.config(bg='#010101')
        self.root.attributes("-transparentcolor", '#010101')
        
        self.canvas = tk.Canvas(self.root, bg='#010101', highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        self.canvas.bind('<ButtonPress-1>', self.on_press)
        self.canvas.bind('<B1-Motion>', self.on_motion)
        self.canvas.bind('<ButtonRelease-1>', self.on_release)
        
        self.update_window_size()

    def update_window_size(self):
        size = self.config['size']
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - size) // 2
        y = (sh - size) // 2
        self.root.geometry(f"{size}x{size}+{x}+{y}")

    def load_pet(self):
        pet_path = os.path.join(self.pets_dir, self.config['selected_pet'])
        if not os.path.exists(pet_path):
            pets = [f for f in os.listdir(self.pets_dir) if f.lower().endswith('.png')]
            if pets:
                self.config['selected_pet'] = pets[0]
                pet_path = os.path.join(self.pets_dir, pets[0])
            else:
                return

        try:
            self.original_img = Image.open(pet_path).convert("RGBA")
            self.render_pet(1.0)
        except Exception as e:
            print(f"Error loading pet: {e}")

    def render_pet(self, scale_factor=1.0):
        if not self.original_img:
            return
            
        target_size = int(self.config['size'] * scale_factor)
        img_w, img_h = self.original_img.size
        
        ratio = min(target_size / img_w, target_size / img_h)
        new_w, new_h = max(1, int(img_w * ratio)), max(1, int(img_h * ratio))
        
        resized = self.original_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(resized)
        
        self.canvas.delete("all")
        self.canvas.create_image(
            self.config['size'] // 2, 
            self.config['size'] // 2, 
            image=self.tk_image, 
            anchor=tk.CENTER
        )

    def on_press(self, event):
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
        if not self.is_dragging:
            self.play_sound()
            self.animate_click()

    def animate_click(self):
        self.render_pet(0.9)
        self.root.after(100, lambda: self.render_pet(1.0))

    def play_sound(self):
        if not self.config['sound_enabled'] or not self.config['selected_sound']:
            return
        sound_path = os.path.join(self.sounds_dir, self.config['selected_sound'])
        if os.path.exists(sound_path) and sound_path.lower().endswith('.wav'):
            winsound.PlaySound(sound_path, winsound.SND_FILENAME | winsound.SND_ASYNC)

    def safe_ui_call(self, func, *args):
        self.root.after(0, lambda: func(*args))

    def create_tray_image(self):
        img = Image.new('RGB', (64, 64), color=(30, 30, 30))
        draw = ImageDraw.Draw(img)
        draw.ellipse((16, 16, 48, 48), fill=(200, 200, 200))
        return img

    def run_tray(self):
        self.tray_icon = pystray.Icon("TynnPet", self.create_tray_image(), "TynnPet")
        self.update_tray_menu()
        self.tray_icon.run()

    def update_tray_menu(self):
        if not self.tray_icon: return
        
        def make_pet_setter(p):
            return lambda icon, item: self.safe_ui_call(self.set_pet, p)
            
        def make_sound_setter(s):
            return lambda icon, item: self.safe_ui_call(self.set_sound, s)

        pets = [f for f in os.listdir(self.pets_dir) if f.lower().endswith('.png')]
        sounds = [f for f in os.listdir(self.sounds_dir) if f.lower().endswith('.wav')]

        pet_items = [item(p, make_pet_setter(p), checked=lambda i, p=p: self.config['selected_pet'] == p) for p in pets]
        
        sound_items = [item(self.t('none'), make_sound_setter(""), checked=lambda i: self.config['selected_sound'] == "")]
        sound_items += [item(s, make_sound_setter(s), checked=lambda i, s=s: self.config['selected_sound'] == s) for s in sounds]

        menu = pystray.Menu(
            item(self.t('made_by'), None, enabled=False),
            pystray.Menu.SEPARATOR,
            item(self.t('sound_on') if self.config['sound_enabled'] else self.t('sound_off'), 
                 lambda: self.safe_ui_call(self.toggle_sound)),
            item(self.t('change_size'), lambda: self.safe_ui_call(self.ask_size)),
            pystray.Menu.SEPARATOR,
            item(self.t('select_pet'), pystray.Menu(*pet_items)),
            item(self.t('select_sound'), pystray.Menu(*sound_items)),
            item(self.t('import_pet'), lambda: self.safe_ui_call(self.import_file, 'pet')),
            item(self.t('import_sound'), lambda: self.safe_ui_call(self.import_file, 'sound')),
            pystray.Menu.SEPARATOR,
            item(self.t('language'), pystray.Menu(
                item('Русский', lambda: self.safe_ui_call(self.set_lang, 'ru'), checked=lambda i: self.config['lang'] == 'ru'),
                item('English', lambda: self.safe_ui_call(self.set_lang, 'en'), checked=lambda i: self.config['lang'] == 'en')
            )),
            item(self.t('github'), lambda: webbrowser.open("https://github.com/kupitonov/DesPet")),
            pystray.Menu.SEPARATOR,
            item(self.t('exit'), lambda: self.safe_ui_call(self.exit_app))
        )
        self.tray_icon.menu = menu

    def create_tray_image(self):
        icon_path = "icon.ico"
        
        if os.path.exists(icon_path):
            return Image.open(icon_path)
        else:
            img = Image.new('RGB', (64, 64), color=(30, 30, 30))
            return img
        
    def toggle_sound(self):
        self.config['sound_enabled'] = not self.config['sound_enabled']
        self.save_config()
        self.update_tray_menu()

    def set_pet(self, pet_name):
        self.config['selected_pet'] = pet_name
        self.save_config()
        self.load_pet()
        self.update_tray_menu()

    def set_sound(self, sound_name):
        self.config['selected_sound'] = sound_name
        self.save_config()
        self.update_tray_menu()

    def set_lang(self, lang):
        self.config['lang'] = lang
        self.save_config()
        self.update_tray_menu()

    def ask_size(self):
        new_size = simpledialog.askinteger(self.app_name, self.t('size_prompt'), 
                                           initialvalue=self.config['size'], minvalue=50, maxvalue=1000)
        if new_size:
            self.config['size'] = new_size
            self.save_config()
            self.update_window_size()
            self.render_pet()

    def import_file(self, ftype):
        if ftype == 'pet':
            path = filedialog.askopenfilename(filetypes=[("PNG Image", "*.png")])
            dest_dir = self.pets_dir
        else:
            path = filedialog.askopenfilename(filetypes=[("WAV Audio", "*.wav")])
            dest_dir = self.sounds_dir

        if path:
            filename = os.path.basename(path)
            dest_path = os.path.join(dest_dir, filename)
            try:
                shutil.copy2(path, dest_path)
                if ftype == 'pet':
                    self.set_pet(filename)
                else:
                    self.set_sound(filename)
            except Exception as e:
                messagebox.showerror(self.t('error'), str(e))

    def exit_app(self):
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.quit()

if __name__ == "__main__":
    app = TynnPetApp()