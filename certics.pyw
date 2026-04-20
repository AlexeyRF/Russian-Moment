import sys
import os
import urllib.request
import zipfile
import subprocess
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QListWidget, 
                             QMessageBox, QProgressBar)
from PyQt6.QtCore import QThread, pyqtSignal, Qt

CERTS_CONFIG = [
    {
        "name": "Корневые сертификаты (Root CA)",
        "url": "https://gu-st.ru/content/lending/windows_russian_trusted_root_ca.zip",
        "zip_file": "root_ca.zip",
        "store": "Root", 
        "files": ["russian_trusted_root_ca_gost_2025.cer", "russian_trusted_root_ca.cer"],
        "delete_query": "Russian Trusted Root CA"
    },
    {
        "name": "Издающие сертификаты (Sub CA)",
        "url": "https://gu-st.ru/content/lending/russian_trusted_sub_ca.zip",
        "zip_file": "sub_ca.zip",
        "store": "CA", 
        "files": ["russian_trusted_sub_ca_gost_2025.cer", "russian_trusted_sub_ca_2024.cer", "russian_trusted_sub_ca.cer"],
        "delete_query": "Russian Trusted Sub CA"
    }
]

WORK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "certs")

class DownloadThread(QThread):
    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    finished = pyqtSignal(bool)

    def run(self):
        try:
            if not os.path.exists(WORK_DIR):
                os.makedirs(WORK_DIR)

            for i, config in enumerate(CERTS_CONFIG):
                zip_path = os.path.join(WORK_DIR, config["zip_file"])
                
                
                self.log.emit(f"Скачивание {config['name']}...")
                urllib.request.urlretrieve(config["url"], zip_path)
                
                self.log.emit(f"Распаковка {config['name']}...")
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(WORK_DIR)
                
                self.progress.emit(int((i + 1) / len(CERTS_CONFIG) * 100))

            self.log.emit("Скачивание и распаковка завершены.")
            self.finished.emit(True)
        except Exception as e:
            self.log.emit(f"Ошибка при скачивании: {str(e)}")
            self.finished.emit(False)


class CertManagerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Менеджер сертификатов Минцифры")
        self.setFixedSize(500, 400)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        self.info_label = QLabel("Управление сертификатами Минцифры России для Windows")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setStyleSheet("font-size: 14px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(self.info_label)

        self.log_list = QListWidget()
        layout.addWidget(self.log_list)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        btn_layout = QHBoxLayout()
        
        self.btn_download = QPushButton("1. Скачать сертификаты")
        self.btn_download.clicked.connect(self.download_certs)
        
        self.btn_install = QPushButton("2. Установить")
        self.btn_install.clicked.connect(self.install_certs)
        
        self.btn_delete = QPushButton("3. Удалить")
        self.btn_delete.clicked.connect(self.delete_certs)
        self.btn_delete.setStyleSheet("background-color: #ffcccc;")

        btn_layout.addWidget(self.btn_download)
        btn_layout.addWidget(self.btn_install)
        btn_layout.addWidget(self.btn_delete)
        
        layout.addLayout(btn_layout)

        self.log("Готово к работе. Сначала скачайте сертификаты.")

    def log(self, message):
        self.log_list.addItem(message)
        self.log_list.scrollToBottom()

    def download_certs(self):
        self.btn_download.setEnabled(False)
        self.progress_bar.setValue(0)
        self.log_list.clear()
        
        self.thread = DownloadThread()
        self.thread.progress.connect(self.progress_bar.setValue)
        self.thread.log.connect(self.log)
        self.thread.finished.connect(self.on_download_finished)
        self.thread.start()

    def on_download_finished(self, success):
        self.btn_download.setEnabled(True)
        if success:
            QMessageBox.information(self, "Успех", "Сертификаты успешно скачаны и готовы к установке.")
        else:
            QMessageBox.critical(self, "Ошибка", "Произошла ошибка при скачивании. Проверьте интернет-соединение.")

    def run_certutil(self, args):
        try:
            result = subprocess.run(["certutil"] + args, 
                                    capture_output=True, text=True, 
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            return result.returncode == 0, result.stdout
        except Exception as e:
            return False, str(e)

    def install_certs(self):
        if not os.path.exists(WORK_DIR):
            QMessageBox.warning(self, "Внимание", "Сначала скачайте сертификаты!")
            return

        self.log("--- НАЧАЛО УСТАНОВКИ ---")
        success_count = 0
        total_files = 0

        for config in CERTS_CONFIG:
            store = config["store"]
            for cert_file in config["files"]:
                total_files += 1
                cert_path = os.path.join(WORK_DIR, cert_file)
                
                if not os.path.exists(cert_path):
                    self.log(f"Файл {cert_file} не найден!")
                    continue
                
                self.log(f"Установка: {cert_file}...")
                success, output = self.run_certutil(["-user", "-addstore", store, cert_path])
                
                if success:
                    self.log(f"✅ {cert_file} установлен.")
                    success_count += 1
                else:
                    self.log(f"❌ Ошибка установки {cert_file}.")

        self.log("--- УСТАНОВКА ЗАВЕРШЕНА ---")
        QMessageBox.information(self, "Отчет", f"Установлено сертификатов: {success_count} из {total_files}.\n\n"
                                             f"Обратите внимание: Windows могла запрашивать подтверждение на установку корневых сертификатов.")

    def delete_certs(self):
        reply = QMessageBox.question(self, 'Подтверждение', 
                                     'Вы уверены, что хотите удалить сертификаты Минцифры из системы?',
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                                     QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            self.log("--- НАЧАЛО УДАЛЕНИЯ ---")
            
            for config in CERTS_CONFIG:
                store = config["store"]
                query = config["delete_query"]
                
                self.log(f"Удаление сертификатов '{query}' из {store}...")
                success, output = self.run_certutil(["-user", "-delstore", store, query])
                
                if success or "Не удается найти" in output:
                    self.log(f"✅ Сертификаты '{query}' удалены (или отсутствовали).")
                else:
                    self.log(f"⚠️ Возникли проблемы при удалении '{query}'. Возможно, они уже удалены.")
            
            self.log("--- УДАЛЕНИЕ ЗАВЕРШЕНА ---")
            QMessageBox.information(self, "Удаление", "Команда на удаление сертификатов выполнена.")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    app.setStyle("Fusion")
    
    window = CertManagerApp()
    window.show()
    sys.exit(app.exec())
