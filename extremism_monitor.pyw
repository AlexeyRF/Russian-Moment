import sys
import os
import json
import csv
import io
import re
import threading
import time
from datetime import datetime
from difflib import SequenceMatcher

import requests
import pyperclip
from plyer import notification
from pynput import keyboard as pynput_keyboard
from PyQt5.QtWidgets import (QApplication, QSystemTrayIcon, QMenu, QAction,
                             QDialog, QVBoxLayout, QLabel, QSlider,
                             QCheckBox, QPushButton, QSpinBox, QGroupBox,
                             QHBoxLayout)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject

URL_MINJUST = "https://minjust.gov.ru/uploaded/files/exportfsm.csv"
CACHE_FILE = "extremism_cache.json"
CONFIG_FILE = "extremism_config.json"
ICON_TITLE = "Монитор экстремизма"
DEFAULT_CONFIG = {
    "enabled": True,
    "max_length": 200,
    "similarity_threshold": 100,
    "fuzzy_match": False,
    "block_enter_on_match": True,
    "notify_on_match": True,
    "monitor_clipboard": True,
    "monitor_keyboard": True,
    "min_phrase_length": 5,
    "min_words": 2
}

def create_russian_flag_icon(size=16):
    from PyQt5.QtGui import QPixmap, QPainter, QColor, QIcon
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    stripe_height = size // 3
    painter.fillRect(0, 0, size, stripe_height, QColor(255, 255, 255))
    painter.fillRect(0, stripe_height, size, stripe_height, QColor(0, 57, 166))
    painter.fillRect(0, 2*stripe_height, size, stripe_height, QColor(213, 43, 30))
    painter.end()
    return QIcon(pixmap)

class RegistryManager:
    def __init__(self):
        self.materials = []
        self._lock = threading.Lock()
        self.load_cached()

    def load_cached(self):
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                self.materials = cache.get("materials", [])
                print(f"Загружено из кэша: {len(self.materials)} записей")
            except Exception as e:
                print(f"Ошибка чтения кэша: {e}")
                self.materials = []

    def download(self):
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            response = requests.get(URL_MINJUST, headers=headers, timeout=30)
            response.raise_for_status()
            content = None
            for enc in ['utf-8-sig', 'utf-8', 'cp1251', 'windows-1251']:
                try:
                    content = response.content.decode(enc)
                    break
                except:
                    continue
            if content is None:
                raise Exception("Не удалось декодировать файл")
            materials = []
            csv_file = io.StringIO(content)
            for delimiter in [';', ',']:
                try:
                    csv_file.seek(0)
                    reader = csv.reader(csv_file, delimiter=delimiter, quotechar='"')
                    header = next(reader, None)
                    if header and len(header) >= 2:
                        for row in reader:
                            if len(row) >= 2:
                                text = row[1].strip()
                                if text:
                                    materials.append({"id": row[0].strip(), "content": text})
                        if materials:
                            break
                except:
                    continue
            if not materials:
                raise Exception("Не удалось распарсить CSV")
            with self._lock:
                self.materials = materials
            cache_data = {"timestamp": datetime.now().isoformat(), "materials": materials}
            with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            return True, f"Загружено {len(materials)} записей"
        except Exception as e:
            return False, str(e)

    def normalize_text(self, text):
        if not text:
            return ""
        text = re.sub(r'\s+', ' ', text)
        return text.lower().strip()

    def check_match(self, text, threshold=100, fuzzy=False, min_len=5, min_words=2):
        text = self.normalize_text(text)
        if not text:
            return False, []
        
        words = re.findall(r'\b\w+\b', text)
        if len(words) < min_words:
            return False, []
        if len(text) < min_len:
            return False, []
        
        matches = []
        
        with self._lock:
            for mat in self.materials:
                material_content = self.normalize_text(mat['content'])
                
                if len(material_content) < 5:
                    continue
                
                if not fuzzy:
                    if material_content in text:
                        matches.append(mat)
                    elif len(material_content) < 50 and text in material_content:
                        matches.append(mat)
                else:
                    ratio = SequenceMatcher(None, text, material_content).ratio() * 100
                    if ratio >= threshold:
                        matches.append(mat)
                    elif (text in material_content or material_content in text):
                        matches.append(mat)
        
        seen_ids = set()
        unique_matches = []
        for m in matches:
            if m['id'] not in seen_ids:
                seen_ids.add(m['id'])
                unique_matches.append(m)
        
        return bool(unique_matches), unique_matches[:10]  

class KeyboardMonitor(QObject):
    match_detected = pyqtSignal(str)
    enter_pressed = pyqtSignal()

    def __init__(self, max_length=200):
        super().__init__()
        self.max_length = max_length
        self.buffer = ""
        self.listener = None
        self.running = False
        self._lock = threading.Lock()
        self._last_check_time = 0

    def start(self):
        if self.running:
            return
        self.running = True
        self.buffer = ""
        self.listener = pynput_keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self.listener.daemon = True
        self.listener.start()

    def stop(self):
        self.running = False
        if self.listener:
            self.listener.stop()
            self.listener = None

    def _on_press(self, key):
        if not self.running:
            return
        try:
            if hasattr(key, 'char') and key.char is not None:
                char = key.char
                with self._lock:
                    self.buffer += char
                    if len(self.buffer) > self.max_length:
                        self.buffer = self.buffer[-self.max_length:]
                self._schedule_check()
            elif key == pynput_keyboard.Key.backspace:
                with self._lock:
                    self.buffer = self.buffer[:-1]
                self._schedule_check()
            elif key == pynput_keyboard.Key.space:
                with self._lock:
                    self.buffer += " "
                self._schedule_check()
        except Exception as e:
            print(f"Keyboard error: {e}")

    def _on_release(self, key):
        if key == pynput_keyboard.Key.enter:
            self.enter_pressed.emit()
            self._check_now()

    def _schedule_check(self):
        current_time = time.time()
        if current_time - self._last_check_time < 0.3:
            return
        self._last_check_time = current_time
        threading.Timer(0.3, self._check_now).start()

    def _check_now(self):
        if not self.running:
            return
        with self._lock:
            text = self.buffer
        if text:
            self.match_detected.emit(text)

    def set_max_length(self, length):
        with self._lock:
            self.max_length = length
            if len(self.buffer) > length:
                self.buffer = self.buffer[-length:]

class ClipboardMonitor(QObject):
    match_detected = pyqtSignal(str)

    def __init__(self, interval=1.0):
        super().__init__()
        self.interval = interval
        self.last_text = ""
        self.timer = None
        self.running = False

    def start(self):
        if self.running:
            return
        self.running = True
        self.last_text = pyperclip.paste()
        self.timer = QTimer()
        self.timer.timeout.connect(self._check)
        self.timer.start(int(self.interval * 1000))

    def stop(self):
        self.running = False
        if self.timer:
            self.timer.stop()
            self.timer = None

    def _check(self):
        if not self.running:
            return
        try:
            current = pyperclip.paste()
            if current != self.last_text and current.strip():
                self.last_text = current
                self.match_detected.emit(current)
        except Exception as e:
            print(f"Clipboard error: {e}")

class ExtremismApp(QApplication):
    def __init__(self, argv):
        super().__init__(argv)
        self.setQuitOnLastWindowClosed(False)
        self.config = self.load_config()
        self.registry = RegistryManager()
        self.keyboard_monitor = KeyboardMonitor(self.config.get("max_length", 200))
        self.clipboard_monitor = ClipboardMonitor()
        
        self.keyboard_monitor.match_detected.connect(self.on_text_input)
        self.clipboard_monitor.match_detected.connect(self.on_text_input)
        self.keyboard_monitor.enter_pressed.connect(self.on_enter_pressed)
        
        self.tray = None
        self.create_tray()
        self.apply_settings()
        if not self.registry.materials:
            self.download_registry_async()
        
        self._save_timer = QTimer()
        self._save_timer.timeout.connect(self._auto_save)
        self._save_timer.start(30000)

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    for k, v in DEFAULT_CONFIG.items():
                        if k not in cfg:
                            cfg[k] = v
                    return cfg
            except:
                pass
        return DEFAULT_CONFIG.copy()

    def save_config(self):
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)

    def _auto_save(self):
        self.save_config()

    def apply_settings(self):
        enabled = self.config.get("enabled", True)
        if enabled:
            if self.config.get("monitor_keyboard", True):
                self.keyboard_monitor.start()
            else:
                self.keyboard_monitor.stop()
            if self.config.get("monitor_clipboard", True):
                self.clipboard_monitor.start()
            else:
                self.clipboard_monitor.stop()
        else:
            self.keyboard_monitor.stop()
            self.clipboard_monitor.stop()
        self.keyboard_monitor.set_max_length(self.config.get("max_length", 200))

    def on_text_input(self, text):
        if not self.config.get("enabled", True):
            return
        
        min_len = self.config.get("min_phrase_length", 5)
        min_words = self.config.get("min_words", 2)
        
        text = re.sub(r'\s+', ' ', text).strip()
        
        if len(text) < min_len:
            return
        
        words = re.findall(r'\b\w+\b', text)
        if len(words) < min_words:
            return

        threshold = self.config.get("similarity_threshold", 100)
        fuzzy = self.config.get("fuzzy_match", False)
        matched, matches = self.registry.check_match(text, threshold, fuzzy, min_len, min_words)
        
        if matched:
            print(f"[MATCH] Найдено совпадение: {matches[0]['content'][:100] if matches else 'Unknown'}")
            
            if len(matches) > 3:
                msg = f"Найдено совпадение с {len(matches)} материалами.\nПример: {matches[0]['content'][:100]}..."
            else:
                msg = "\n".join([f"- {m['content'][:100]}" for m in matches[:3]])
            
            if self.config.get("notify_on_match", True):
                try:
                    notification.notify(
                        title="⚠️ Обнаружен экстремистский материал",
                        message=msg,
                        app_name=ICON_TITLE,
                        timeout=8
                    )
                except:
                    pass
            self.last_match_time = time.time()

    def on_enter_pressed(self):
        if not self.config.get("block_enter_on_match", True):
            return
        if hasattr(self, 'last_match_time') and (time.time() - self.last_match_time) < 2:
            try:
                notification.notify(
                    title="⛔ Блокировка Enter",
                    message="Клавиша Enter заблокирована из-за обнаруженного совпадения.",
                    timeout=3
                )
            except:
                pass
            try:
                import keyboard
                keyboard.block_key('enter')
                QTimer.singleShot(500, lambda: keyboard.unblock_key('enter'))
            except ImportError:
                pass

    def download_registry_async(self):
        def task():
            success, msg = self.registry.download()
            if success:
                self.show_tray_message("База обновлена", msg)
            else:
                self.show_tray_message("Ошибка обновления", msg)
        threading.Thread(target=task, daemon=True).start()

    def show_tray_message(self, title, msg, timeout=3):
        if self.tray:
            self.tray.showMessage(title, msg, QSystemTrayIcon.Information, timeout * 1000)

    def create_tray(self):
        self.tray = QSystemTrayIcon()
        self.tray.setIcon(create_russian_flag_icon(16))
        self.tray.setToolTip(ICON_TITLE)
        self.tray_menu = QMenu()
        self.tray.setContextMenu(self.tray_menu)
        self.tray.show()
        self.update_menu()
        self.tray.activated.connect(self.on_tray_click)

    def on_tray_click(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_settings_dialog()

    def update_menu(self):
        self.tray_menu.clear()
        status = "Включён" if self.config["enabled"] else "Выключен"
        status_action = QAction(f"Статус: {status}", self.tray_menu)
        status_action.setEnabled(False)
        self.tray_menu.addAction(status_action)
        self.tray_menu.addSeparator()
        
        toggle_action = QAction("Выключить мониторинг" if self.config["enabled"] else "Включить мониторинг", self.tray_menu)
        toggle_action.triggered.connect(self.toggle_monitoring)
        self.tray_menu.addAction(toggle_action)
        
        settings_action = QAction("Настройки...", self.tray_menu)
        settings_action.triggered.connect(self.show_settings_dialog)
        self.tray_menu.addAction(settings_action)
        
        update_action = QAction("Обновить базу Минюста", self.tray_menu)
        update_action.triggered.connect(self.download_registry_async)
        self.tray_menu.addAction(update_action)
        
        self.tray_menu.addSeparator()
        info_action = QAction(f"Записей в реестре: {len(self.registry.materials)}", self.tray_menu)
        info_action.setEnabled(False)
        self.tray_menu.addAction(info_action)
        
        self.tray_menu.addSeparator()
        exit_action = QAction("Выход", self.tray_menu)
        exit_action.triggered.connect(self.exit_app)
        self.tray_menu.addAction(exit_action)

    def toggle_monitoring(self):
        self.config["enabled"] = not self.config["enabled"]
        self.save_config()
        self.apply_settings()
        self.update_menu()
        status = "включён" if self.config["enabled"] else "выключен"
        self.show_tray_message("Мониторинг", f"Мониторинг {status}")

    def show_settings_dialog(self):
        dialog = QDialog()
        dialog.setWindowTitle("Настройки монитора экстремизма")
        dialog.setMinimumWidth(450)
        layout = QVBoxLayout(dialog)

        group_gen = QGroupBox("Общие")
        gen_layout = QVBoxLayout()
        self.cb_enabled = QCheckBox("Включить мониторинг")
        self.cb_enabled.setChecked(self.config["enabled"])
        gen_layout.addWidget(self.cb_enabled)
        self.cb_keyboard = QCheckBox("Мониторить клавиатуру")
        self.cb_keyboard.setChecked(self.config.get("monitor_keyboard", True))
        gen_layout.addWidget(self.cb_keyboard)
        self.cb_clipboard = QCheckBox("Мониторить буфер обмена")
        self.cb_clipboard.setChecked(self.config.get("monitor_clipboard", True))
        gen_layout.addWidget(self.cb_clipboard)
        self.cb_notify = QCheckBox("Показывать уведомления")
        self.cb_notify.setChecked(self.config.get("notify_on_match", True))
        gen_layout.addWidget(self.cb_notify)
        self.cb_block_enter = QCheckBox("Блокировать Enter при совпадении")
        self.cb_block_enter.setChecked(self.config.get("block_enter_on_match", True))
        gen_layout.addWidget(self.cb_block_enter)
        group_gen.setLayout(gen_layout)
        layout.addWidget(group_gen)

        group_an = QGroupBox("Анализ текста")
        an_layout = QVBoxLayout()
        
        len_layout = QHBoxLayout()
        len_layout.addWidget(QLabel("Макс. длина буфера (символов):"))
        self.spin_length = QSpinBox()
        self.spin_length.setRange(10, 1000)
        self.spin_length.setValue(self.config.get("max_length", 200))
        len_layout.addWidget(self.spin_length)
        an_layout.addLayout(len_layout)

        min_len_layout = QHBoxLayout()
        min_len_layout.addWidget(QLabel("Минимальная длина фразы (символов):"))
        self.spin_min_len = QSpinBox()
        self.spin_min_len.setRange(3, 200)
        self.spin_min_len.setValue(self.config.get("min_phrase_length", 5))
        min_len_layout.addWidget(self.spin_min_len)
        an_layout.addLayout(min_len_layout)

        min_words_layout = QHBoxLayout()
        min_words_layout.addWidget(QLabel("Минимальное количество слов:"))
        self.spin_min_words = QSpinBox()
        self.spin_min_words.setRange(1, 10)
        self.spin_min_words.setValue(self.config.get("min_words", 2))
        min_words_layout.addWidget(self.spin_min_words)
        an_layout.addLayout(min_words_layout)

        self.cb_fuzzy = QCheckBox("Нечёткое сравнение (похожесть)")
        self.cb_fuzzy.setChecked(self.config.get("fuzzy_match", False))
        an_layout.addWidget(self.cb_fuzzy)

        thresh_layout = QHBoxLayout()
        thresh_layout.addWidget(QLabel("Порог схожести (%):"))
        self.slider_thresh = QSlider(Qt.Horizontal)
        self.slider_thresh.setRange(50, 100)
        self.slider_thresh.setValue(self.config.get("similarity_threshold", 100))
        self.slider_thresh.valueChanged.connect(lambda v: self.label_thresh.setText(f"{v}%"))
        thresh_layout.addWidget(self.slider_thresh)
        self.label_thresh = QLabel(f"{self.slider_thresh.value()}%")
        thresh_layout.addWidget(self.label_thresh)
        an_layout.addLayout(thresh_layout)

        group_an.setLayout(an_layout)
        layout.addWidget(group_an)

        
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("Сохранить")
        btn_cancel = QPushButton("Отмена")
        btn_layout.addWidget(btn_save)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

        def save():
            self.config["enabled"] = self.cb_enabled.isChecked()
            self.config["monitor_keyboard"] = self.cb_keyboard.isChecked()
            self.config["monitor_clipboard"] = self.cb_clipboard.isChecked()
            self.config["notify_on_match"] = self.cb_notify.isChecked()
            self.config["block_enter_on_match"] = self.cb_block_enter.isChecked()
            self.config["max_length"] = self.spin_length.value()
            self.config["min_phrase_length"] = self.spin_min_len.value()
            self.config["min_words"] = self.spin_min_words.value()
            self.config["fuzzy_match"] = self.cb_fuzzy.isChecked()
            self.config["similarity_threshold"] = self.slider_thresh.value()
            self.save_config()
            self.apply_settings()
            self.update_menu()
            dialog.accept()
            self.show_tray_message("Настройки сохранены", "Параметры обновлены")

        btn_save.clicked.connect(save)
        btn_cancel.clicked.connect(dialog.reject)
        dialog.exec_()

    def exit_app(self):
        self.save_config()
        self.keyboard_monitor.stop()
        self.clipboard_monitor.stop()
        self.quit()

if __name__ == "__main__":
    app = ExtremismApp(sys.argv)
    sys.exit(app.exec_())
