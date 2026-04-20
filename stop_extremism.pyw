import sys
import os
import csv
import json
import requests
import re
import platform
import difflib
import time
from datetime import datetime, timedelta
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLineEdit, QTableWidget, 
                             QTableWidgetItem, QMessageBox, QHeaderView, QLabel, 
                             QProgressBar)
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QPalette, QColor, QFont

POPULAR_DOMAINS = {
    'vk.com', 'youtube.com', 'google.com', 'yandex.ru', 'ok.ru', 
    'mail.ru', 't.me', 'facebook.com', 'instagram.com', 'twitter.com',
    'tiktok.com', 'whatsapp.com', 'telegram.org'
}

URL_MINJUST = "https://minjust.gov.ru/uploaded/files/exportfsm.csv"
CACHE_FILE = "materials_cache.json"

class DownloadThread(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def run(self):
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/csv,application/csv,text/plain,*/*',
                'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Referer': 'https://minjust.gov.ru/',
            }
            
            response = requests.get(URL_MINJUST, headers=headers, timeout=30)
            response.raise_for_status()
            
            content = None
            for encoding in ['utf-8-sig', 'utf-8', 'cp1251', 'windows-1251']:
                try:
                    content = response.content.decode(encoding)
                    break
                except:
                    continue
            
            if content is None:
                raise Exception("Не удалось декодировать файл")
            
            import io
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
                                material_text = row[1].strip()
                                if material_text:
                                    materials.append({
                                        "id": row[0].strip(), 
                                        "content": material_text
                                    })
                        if materials:
                            break
                except:
                    continue
            
            if not materials:
                raise Exception("Не удалось распарсить CSV файл")
            
            cache_data = {
                "timestamp": datetime.now().isoformat(),
                "materials": materials
            }
            with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            
            self.finished.emit(materials)
        except Exception as e:
            self.error.emit(str(e))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Менеджер блокировок материалов Минюста")
        self.resize(1000, 700)
        
        self.materials = []
        self.filtered_materials = []
        self.domains_to_block = []
        
        self.initUI()
        self.apply_dark_theme()
        self.load_cached_data()
        
        self.search_timer = None
        self.search_input.textChanged.connect(self.on_search_text_changed)

    def apply_dark_theme(self):
        dark_palette = QPalette()
        
        dark_color = QColor(30, 30, 30)
        darker_color = QColor(20, 20, 20)
        light_color = QColor(50, 50, 50)
        text_color = QColor(220, 220, 220)
        highlight_color = QColor(60, 140, 220)
        button_color = QColor(60, 60, 65)
        button_hover = QColor(75, 75, 80)
        
        dark_palette.setColor(QPalette.Window, dark_color)
        dark_palette.setColor(QPalette.WindowText, text_color)
        dark_palette.setColor(QPalette.Base, darker_color)
        dark_palette.setColor(QPalette.AlternateBase, dark_color)
        dark_palette.setColor(QPalette.ToolTipBase, text_color)
        dark_palette.setColor(QPalette.ToolTipText, text_color)
        dark_palette.setColor(QPalette.Text, text_color)
        dark_palette.setColor(QPalette.Button, button_color)
        dark_palette.setColor(QPalette.ButtonText, text_color)
        dark_palette.setColor(QPalette.BrightText, QColor(255, 100, 100))
        dark_palette.setColor(QPalette.Link, highlight_color)
        dark_palette.setColor(QPalette.Highlight, highlight_color)
        dark_palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
        
        self.setPalette(dark_palette)
        
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e1e;
            }
            QWidget {
                background-color: #1e1e1e;
                color: #dcdcdc;
            }
            QTableWidget {
                background-color: #252525;
                gridline-color: #404040;
                selection-background-color: #3c8cdc;
                selection-color: white;
                alternate-background-color: #2a2a2a;
            }
            QTableWidget::item {
                padding: 5px;
                color: #dcdcdc;
            }
            QTableWidget::item:selected {
                background-color: #3c8cdc;
                color: white;
            }
            QHeaderView::section {
                background-color: #3c3c3c;
                padding: 5px;
                border: 1px solid #4a4a4a;
                color: #dcdcdc;
                font-weight: bold;
            }
            QPushButton {
                background-color: #3c3c41;
                border: 1px solid #4a4a4a;
                border-radius: 4px;
                padding: 6px 12px;
                color: #dcdcdc;
                font-weight: bold;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #4a4a50;
                border-color: #5a5a60;
            }
            QPushButton:pressed {
                background-color: #2a2a2f;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                color: #808080;
            }
            QLineEdit {
                background-color: #2a2a2a;
                border: 1px solid #4a4a4a;
                border-radius: 4px;
                padding: 6px;
                color: #dcdcdc;
                selection-background-color: #3c8cdc;
            }
            QLineEdit:focus {
                border-color: #3c8cdc;
            }
            QProgressBar {
                border: 1px solid #4a4a4a;
                border-radius: 4px;
                text-align: center;
                color: #dcdcdc;
                background-color: #2a2a2a;
            }
            QProgressBar::chunk {
                background-color: #3c8cdc;
                border-radius: 3px;
            }
            QLabel {
                color: #dcdcdc;
            }
            QMessageBox {
                background-color: #2a2a2a;
                color: #dcdcdc;
            }
            QMessageBox QPushButton {
                min-width: 70px;
            }
        """)

    def load_cached_data(self):
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                
                cache_time = datetime.fromisoformat(cache_data["timestamp"])
                now = datetime.now()
                
                if now - cache_time > timedelta(days=30):
                    self.lbl_status.setText("⚠ Кэш устарел (старше месяца). Нажмите 'Скачать базу' для обновления.")
                    self.materials = cache_data["materials"]
                    self.filtered_materials = self.materials[:100]
                    self.display_data(self.filtered_materials)
                    self.lbl_status.setText(f"Загружено из устаревшего кэша: {len(self.materials)} записей")
                else:
                    self.materials = cache_data["materials"]
                    self.filtered_materials = self.materials[:100]
                    self.display_data(self.filtered_materials)
                    days_old = (now - cache_time).days
                    self.lbl_status.setText(f"✓ Загружено из кэша: {len(self.materials)} записей (возраст: {days_old} дней)")
            except Exception as e:
                self.lbl_status.setText(f"✗ Ошибка загрузки кэша: {str(e)}")
        else:
            self.lbl_status.setText("ℹ Кэш не найден. Нажмите 'Скачать базу' для загрузки данных.")

    def initUI(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(10)

        control_layout = QHBoxLayout()
        control_layout.setSpacing(10)
        
        self.btn_download = QPushButton("📥 Скачать базу")
        self.btn_download.clicked.connect(self.download_data)
        self.btn_download.setMinimumWidth(120)
        control_layout.addWidget(self.btn_download)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Поиск по тексту (автоматически)...")
        control_layout.addWidget(self.search_input)

        layout.addLayout(control_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("Ожидание загрузки данных...")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["ID", "Описание материала"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)
        
        export_layout = QHBoxLayout()
        export_layout.setSpacing(10)
        
        self.btn_generate_proxybridge = QPushButton("🔒 ProxyBridge блокировки")
        self.btn_generate_proxybridge.clicked.connect(lambda: self.generate_blocks("proxybridge"))
        self.btn_generate_proxybridge.setMinimumWidth(150)
        export_layout.addWidget(self.btn_generate_proxybridge)
        
        self.btn_generate_hosts = QPushButton("🖥 Hosts блокировки")
        self.btn_generate_hosts.clicked.connect(lambda: self.generate_blocks("hosts"))
        self.btn_generate_hosts.setMinimumWidth(150)
        export_layout.addWidget(self.btn_generate_hosts)
        
        self.btn_generate_both = QPushButton("📦 Оба типа блокировок")
        self.btn_generate_both.clicked.connect(lambda: self.generate_blocks("both"))
        self.btn_generate_both.setMinimumWidth(150)
        export_layout.addWidget(self.btn_generate_both)

        layout.addLayout(export_layout)

    def on_search_text_changed(self):
        if self.search_timer is not None:
            self.search_timer.stop()
        
        from PyQt5.QtCore import QTimer
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self.search_data)
        self.search_timer.start(500)

    def download_data(self):
        self.btn_download.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.lbl_status.setText("Скачивание данных с сайта Минюста...")
        
        self.thread = DownloadThread()
        self.thread.finished.connect(self.on_download_finished)
        self.thread.error.connect(self.on_download_error)
        self.thread.start()

    def on_download_finished(self, data):
        self.materials = data
        self.progress_bar.setVisible(False)
        self.btn_download.setEnabled(True)
        self.lbl_status.setText(f"✓ Загружено записей: {len(self.materials)}")
        self.search_data()

    def on_download_error(self, err):
        self.progress_bar.setVisible(False)
        self.btn_download.setEnabled(True)
        QMessageBox.critical(self, "Ошибка", f"Не удалось скачать базу:\n{err}")
        self.lbl_status.setText("✗ Ошибка скачивания.")

    def display_data(self, data):
        self.table.setRowCount(len(data))
        for row, item in enumerate(data):
            self.table.setItem(row, 0, QTableWidgetItem(str(item['id'])))
            content = item['content']
            if content.startswith('"') and content.endswith('"'):
                content = content[1:-1]
            self.table.setItem(row, 1, QTableWidgetItem(content))
        
        self.table.resizeColumnToContents(0)

    def search_data(self):
        query = self.search_input.text().lower().strip()
        if not query:
            self.filtered_materials = self.materials[:100]
            self.display_data(self.filtered_materials)
            self.lbl_status.setText(f"📊 Всего записей: {len(self.materials)} (показано первых 100)")
            return

        results = []
        for item in self.materials:
            content_lower = item['content'].lower()
            
            if query in content_lower:
                results.append(item)
                continue
                
            if len(query) > 3:
                sm = difflib.SequenceMatcher(None, query, content_lower)
                match = sm.find_longest_match(0, len(query), 0, min(len(content_lower), len(query) * 2))
                if match.size >= len(query) * 0.6:
                    results.append(item)

        self.filtered_materials = results
        self.display_data(results[:1000])
        self.lbl_status.setText(f"🔍 Найдено совпадений: {len(results)}")

    def extract_domains_from_text(self):
        domain_pattern = r'\b(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+(?:ru|com|org|net|info|biz|рф|su|рф|ua|by|kz|uz|md|am|ge)\b'
        extracted = set()
        
        for item in self.filtered_materials:
            found = re.findall(domain_pattern, item['content'].lower(), re.IGNORECASE)
            for d in found:
                if len(d) > 4 and '.' in d:
                    extracted.add(d)
        
        return list(extracted)

    def generate_blocks(self, block_type):
        if not self.materials:
            QMessageBox.warning(self, "Пусто", "Сначала скачайте базу!")
            return

        all_domains = self.extract_domains_from_text()
        
        if not all_domains:
            QMessageBox.information(self, "Результат", "Домены для блокировки не найдены в отфильтрованных материалах.")
            return
            
        final_domains_to_block = []

        for domain in all_domains:
            is_popular = False
            for pop in POPULAR_DOMAINS:
                if pop in domain:
                    is_popular = True
                    break
            
            if is_popular:
                reply = QMessageBox.question(
                    self, 'Популярный домен',
                    f'Домен "{domain}" найден в списке.\nОн относится к крупным ресурсам. Добавить его в блокировку?',
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    final_domains_to_block.append(domain)
            else:
                final_domains_to_block.append(domain)

        if not final_domains_to_block:
            QMessageBox.information(self, "Результат", "Нет доменов для блокировки.")
            return

        if block_type in ["proxybridge", "both"]:
            self.create_proxybridge_config(final_domains_to_block)
        
        if block_type in ["hosts", "both"]:
            self.add_to_hosts(final_domains_to_block)

    def create_proxybridge_config(self, domains):
        hosts_string = "; ".join(domains)
        
        rule = {
            "processNames": "*",
            "targetHosts": hosts_string,
            "targetPorts": "*",
            "protocol": "BOTH",
            "action": "BLOCK",
            "enabled": True
        }

        try:
            filename = "ProxyBridge-Rules.json"
            with open(filename, "w", encoding="utf-8") as f:
                json.dump([rule], f, indent=2, ensure_ascii=False)
            QMessageBox.information(self, "Успех", 
                f"✅ Файл {filename} успешно создан.\nЗаблокировано доменов: {len(domains)}\n\nДомены:\n" + 
                "\n".join(domains[:20]) + ("\n..." if len(domains) > 20 else ""))
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить JSON: {str(e)}")

    def add_to_hosts(self, domains):
        if platform.system() == 'Windows':
            hosts_path = r'C:\Windows\System32\drivers\etc\hosts'
        else:
            hosts_path = '/etc/hosts'

        try:
            with open(hosts_path, 'r', encoding='utf-8') as f:
                existing_lines = f.read()

            new_entries = []
            for domain in domains:
                if f" {domain}" not in existing_lines and domain not in existing_lines:
                    new_entries.append(f"127.0.0.1 {domain}")

            if not new_entries:
                QMessageBox.information(self, "Hosts", "Все домены уже присутствуют в файле hosts.")
                return

            with open(hosts_path, 'a', encoding='utf-8') as f:
                f.write(f"\n# Добавлено менеджером блокировок Минюста {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("\n".join(new_entries) + "\n")
                
            QMessageBox.information(self, "Успех", 
                f"✅ В файл hosts ({hosts_path}) успешно добавлено {len(new_entries)} доменов.\n\nДомены:\n" +
                "\n".join(domains[:20]) + ("\n..." if len(domains) > 20 else ""))

        except PermissionError:
            QMessageBox.critical(self, "Ошибка доступа", 
                f"❌ Нет прав для редактирования файла {hosts_path}.\n\n"
                "Пожалуйста, запустите программу от имени Администратора (Windows) или через sudo (Linux/macOS).")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось изменить файл hosts: {str(e)}")


if __name__ == '__main__':
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())