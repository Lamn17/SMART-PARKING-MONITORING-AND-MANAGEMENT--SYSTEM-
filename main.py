import sys
import cv2
import numpy as np
import time
from PyQt5 import uic
from PyQt5.QtMultimedia import QCameraInfo
from PyQt5.QtWidgets import QApplication, QMainWindow, QMessageBox, QTableWidget, QTableWidgetItem, QPushButton, QVBoxLayout, QDialog
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import QThread, pyqtSignal, pyqtSlot, QTimer
import serial
import json
import os
import importlib.util   # <-- thêm dòng này
from datetime import datetime
from car_parking_check import check_parking_occupancy

sys.path.append("code_palate_detect")


class HistoryPopup(QDialog):
    def __init__(self, parking_manager):
        super().__init__()
        self.setWindowTitle("History")
        self.resize(700, 400)

        self.parking_manager = parking_manager
        self.table = QTableWidget()
        self.btn_close = QPushButton("Exit")
        self.btn_close.clicked.connect(self.close)

        layout = QVBoxLayout()
        layout.addWidget(self.table)
        layout.addWidget(self.btn_close)
        self.setLayout(layout)

        self.populate_table()

    def populate_table(self):
        history = self.parking_manager.get_history()
        self.table.setRowCount(len(history))
        self.table.setColumnCount(3)

        self.table.setHorizontalHeaderLabels(["Car", "Time in", "License Plate Recognized"])
        for row, entry in enumerate(history):
            self.table.setItem(row, 0, QTableWidgetItem(entry["plate"]))
            self.table.setItem(row, 1, QTableWidgetItem(entry["time_in"]))
            self.table.setItem(row, 2, QTableWidgetItem(entry.get("License Plate Recognized")))


        self.table.resizeColumnsToContents()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)


class ParkingManager:
    def __init__(self, file_path="parking_data.json", history_path="history.json", serial_thread=None):
        self.file_path = file_path
        self.history_path = history_path
        self.serial_thread = serial_thread

        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = []

        try:
            with open(self.history_path, 'r', encoding='utf-8') as f:
                self.history = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.history = []

    def save_data(self):
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=4)

    def save_history(self):
        with open(self.history_path, 'w', encoding='utf-8') as f:
            json.dump(self.history, f, ensure_ascii=False, indent=4)

    def add_check_in(self, plate):
        if len(self.data) >= 6:
            return f"Bãi xe đã đầy. Không thể nhận thêm xe {plate}."

        for entry in self.data:
            if entry["plate"] == plate:
                return f"Xe {plate} đã có trong bãi, không cần lưu thêm."

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        image_path = f"save/check_in/{now}_plate.jpg"
        self.history.append({
            "plate": plate,
            "time_in": now,
            "License Plate Recognized": image_path
        })
        self.data.append({
            "plate": plate,
            "time_in": now
        })
        self.save_data()
        print(f"Đã lưu lượt vào: {plate} lúc {now}")

        if self.serial_thread:
            self.serial_thread.send_command("OPEN_IN")

        return f"Đã nhận xe: {plate} lúc {now}"

    def add_check_out(self, plate):
        for i in range(len(self.data) - 1, -1, -1):
            entry = self.data[i]
            if entry["plate"] == plate:
                time_in = datetime.strptime(entry["time_in"], "%Y-%m-%d %H:%M:%S")
                time_out = datetime.now()
                duration = time_out - time_in
                duration_str = str(duration).split('.')[0]

                seconds = duration.total_seconds()
                if seconds <= 30:
                    tien = "5.000 VND"
                elif seconds <= 40:
                    tien = "10.000 VND"
                else:
                    tien = "15.000 VND"

                image_path = f"save/check_in/{datetime.now().strftime('%Y%m%d_%H%M%S')}_plate.jpg"

                self.history.append({
                    "plate": plate,
                    "time_in": entry["time_in"],
                    "time_out": time_out.strftime("%Y-%m-%d %H:%M:%S"),
                    "duration": duration_str,
                    "fee": tien,
                    "License Plate Recognized": image_path
                })
                self.save_history()

                del self.data[i]
                self.save_data()

                if self.serial_thread:
                    self.serial_thread.send_command("OPEN_OUT")

                return time_in, time_out, duration, tien, ""

        return None, None, None, None, f"Không tìm thấy lượt vào của {plate}"

    def get_all_logs(self):
        return self.data

    def get_history(self):
        return self.history


class DateTime(QThread):
    time_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.running = True

    def run(self):
        while self.running:
            time.sleep(1)
            now = datetime.now()
            current_time = now.strftime("%H:%M:%S")
            self.time_signal.emit(current_time)

    def stop(self):
        self.running = False
        self.quit()
        self.wait()


class SerialThread(QThread):
    data_received = pyqtSignal(str)

    def __init__(self, port="COM4", baud=9600):
        super().__init__()
        self.port = port
        self.baud = baud
        self.serial_conn = None
        self.running = True

    def run(self):
        try:
            self.serial_conn = serial.Serial(self.port, self.baud, timeout=1)
            time.sleep(2)
            while self.running:
                if self.serial_conn.in_waiting:
                    line = self.serial_conn.readline().decode('utf-8').strip()
                    if line:
                        self.data_received.emit(line)
        except Exception as e:
            print("Serial error:", e)
        finally:
            if self.serial_conn and self.serial_conn.is_open:
                self.serial_conn.close()

    def send_command(self, cmd):
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.write((cmd + "\n").encode())
            print(f"[Python → UNO] {cmd}")

    def stop(self):
        self.running = False
        self.wait()


class CameraThread(QThread):
    ImageUpdate = pyqtSignal(np.ndarray)
    FPS = pyqtSignal(int)

    def __init__(self, cam_index):
        super().__init__()
        self.cam_index = cam_index
        self.running = False
        self.cap = None

    def run(self):
        print(f"[CameraThread] Đang khởi động camera index {self.cam_index}...")
        self.cap = cv2.VideoCapture(self.cam_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        if not self.cap.isOpened():
            print(f"Không thể mở camera {self.cam_index}")
            return

        print(f"Camera {self.cam_index} đã sẵn sàng")
        self.running = True
        prev_time = time.time()

        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                print("Lỗi đọc frame từ camera.")
                time.sleep(0.2)
                continue

            frame = cv2.flip(frame, -1)
            now = time.time()
            fps = 1 / (now - prev_time + 1e-5)
            prev_time = now
            self.ImageUpdate.emit(frame)
            self.FPS.emit(int(fps))

        print(f"[CameraThread] Đã dừng camera {self.cam_index}")
        self.cap.release()

    def stop(self):
        print(f"[CameraThread] Yêu cầu dừng camera {self.cam_index}")
        self.running = False
        self.quit()
        self.wait()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        file_path = "code_palate_detect/detect_plate_and_compare.py"
        spec = importlib.util.spec_from_file_location("detect_plate_and_compare", file_path)
        self.plate_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.plate_module)

        self.last_check_time = 0
        uic.loadUi("ui_code/ui_demo.ui", self)

        self.online_cam = QCameraInfo.availableCameras()
        for idx, cam in enumerate(self.online_cam, start=1):
            self.camlist.addItem(f"Cam:{idx}: {cam.description()}")

        self.btn_start.clicked.connect(self.StartWebCam)
        self.btn_ref.clicked.connect(self.LoadWebcam)
        self.btn_stop.clicked.connect(self.StopWebcam)
        self.BT_IN.clicked.connect(self.run_check_from_camera_in)
        self.BT_OUT.clicked.connect(self.run_check_from_camera_out)
        self.QUIT.clicked.connect(self.confirm_exit)
        self.HISTORY.clicked.connect(self.show_history_popup)

        self.serial_thread = SerialThread(port="COM4")
        self.serial_thread.data_received.connect(self.handle_serial_data)
        self.serial_thread.start()

        self.parking_manager = ParkingManager(serial_thread=self.serial_thread)
        self.check_xe_yolo = 0

        self.datetime_thread = DateTime()
        self.datetime_thread.time_signal.connect(self.update_time_label)
        self.datetime_thread.start()

        self.camera_threads = {}
        self.latest_check_frame = None
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self.check_parking_camera)
        self.check_timer.start(500)

    def check_parking_camera(self):
        thread = self.camera_threads.get(2)
        if not thread or not thread.running:
            return
        if self.latest_check_frame is None:
            return
        frame = self.latest_check_frame.copy()
        annotated, slot_results, empty_slots = check_parking_occupancy(frame)
        if empty_slots:
            message = ",".join(empty_slots)
        else:
            message = "FULL"
        self.serial_thread.send_command(f"SLOTS:{message}")
        pixmap = self.cvt_cv_qt(annotated)
        self.disp_main_check.setPixmap(pixmap)
        count = sum(1 for r in slot_results if r['status'] == 'Occupied')
        num_xe_con_lai = 6 - count
        self.check_xe_yolo = count
        if hasattr(self, 'lb_con_lai'):
            self.lb_so_xe.setText(str(count))
            self.lb_con_lai.setText(str(num_xe_con_lai))
        print(f"Số xe đang đỗ: {count}")

    def show_history_popup(self):
        popup = HistoryPopup(self.parking_manager)
        popup.exec_()

    def confirm_exit(self):
        reply = QMessageBox.question(
            self,
            "Xác nhận thoát",
            "Bạn có chắc chắn muốn thoát chương trình?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.close()

    def closeEvent(self, event):
        try:
            self.datetime_thread.stop()
        except:
            pass
        try:
            self.serial_thread.stop()
        except:
            pass
        try:
            for thread in self.camera_threads.values():
                thread.stop()
        except:
            pass
        event.accept()

    def update_time_label(self, current_time):
        self.thoi_gian.setText(current_time)

    def handle_serial_data(self, data: str):
        data = data.strip()
        print(f"[UNO → PC] {data}")

        if data == "SENSOR_IN":
            self.run_check_from_camera_in()
        elif data == "CLEAR_IN":
            self.serial_thread.send_command("CLOSE_IN")
        elif data == "SENSOR_OUT":
            self.run_check_from_camera_out()
        elif data == "CLEAR_OUT":
            self.serial_thread.send_command("CLOSE_OUT")
        elif data.startswith("PLATE:"):
            plate = data.split(":", 1)[1].strip()
            print(f"[UNO] Biển số gửi lên: {plate}")
        elif data.startswith("SLOTS:"):
            slots_info = data.split(":", 1)[1].strip()
            print(f"[UNO] Thông tin slot: {slots_info}")
        else:
            print(f"[UNO] Gói tin không xác định: {data}")

    def run_check_from_camera_in(self):
        pixmap = self.disp_main_in.pixmap()
        if pixmap is None:
            print("Không có ảnh từ camera_in.")
            return
        image = pixmap.toImage().convertToFormat(QImage.Format_RGB888)
        width = image.width()
        height = image.height()
        ptr = image.bits()
        ptr.setsize(image.byteCount())
        arr = np.array(ptr).reshape(height, width, 3)
        frame = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        self.check_in(frame)

    def run_check_from_camera_out(self):
        pixmap = self.disp_main_out.pixmap()
        if pixmap is None:
            print("Không có ảnh từ camera_out.")
            return
        image = pixmap.toImage().convertToFormat(QImage.Format_RGB888)
        width = image.width()
        height = image.height()
        ptr = image.bits()
        ptr.setsize(image.byteCount())
        arr = np.array(ptr).reshape(height, width, 3)
        frame = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        self.check_out(frame)

    def check_in(self, frame):
        plates, annotated = self.plate_module.detect_plate_and_compare(frame)
        if plates:
            self.lb_bien_vao.setText(str(plates))
            for plate in plates:
                log = self.parking_manager.add_check_in(plate)
                self.serial_thread.send_command(f"PLATE:{plate}")
                print(log)
            save_dir = "save/check_in"
            os.makedirs(save_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            img_filename = os.path.join(save_dir, f"{timestamp}_plate.jpg")
            txt_filename = os.path.join(save_dir, f"{timestamp}_plate.txt")
            cv2.imwrite(img_filename, annotated)
            with open(txt_filename, "w", encoding="utf-8") as f:
                for plate in plates:
                    f.write(plate + "\n")

            if self.parking_manager.history:
                self.parking_manager.history[-1]["License Plate Recognized"] = img_filename
                self.parking_manager.save_history()
            self.serial_thread.send_command("OPEN_OUT")
        else:
            self.lb_bien_vao.setText("Không nhận diện được biển số")

    def check_out(self, frame):
        plates, annotated = self.plate_module.detect_plate_and_compare(frame)
        if plates:
            self.lb_bien_ra.setText(str(plates))
            for plate in plates:
                self.serial_thread.send_command(f"PLATE:{plate}")
                time_in, time_out, duration, tien, log = self.parking_manager.add_check_out(plate)
                if time_in:
                    self.lb_tgian_vao.setText(str(time_in))
                    self.lb_tgian_ra.setText(time_out.strftime('%H:%M:%S'))
                    self.lb_tgian_tong.setText(str(duration).split('.')[0])
                    self.tien.setText(tien)
                else:
                    print(log)
            save_dir = "save/check_out"
            os.makedirs(save_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            img_filename = os.path.join(save_dir, f"{timestamp}_plate.jpg")
            txt_filename = os.path.join(save_dir, f"{timestamp}_plate.txt")
            cv2.imwrite(img_filename, annotated)
            with open(txt_filename, "w", encoding="utf-8") as f:
                for plate in plates:
                    f.write(plate + "\n")
            self.serial_thread.send_command("OPEN_OUT")
        else:
            self.lb_bien_ra.setText("Không nhận diện được biển số")

    def LoadWebcam(self):
        self.online_cam = QCameraInfo.availableCameras()
        self.camlist.clear()
        running_indices = []
        for thread in self.camera_threads.values():
            if thread and thread.cap and thread.cap.isOpened():
                running_indices.append(thread.cam_index)

        for idx, cam in enumerate(self.online_cam):
            label = f"Cam:{idx+1}: {cam.description()}"
            if idx in running_indices:
                label += "  [RUN]"
            self.camlist.addItem(label)

    def StopWebcam(self, logical_id: int):
        if logical_id in self.camera_threads:
            self.camera_threads[logical_id].stop()
            del self.camera_threads[logical_id]

    def start_camera(self, logical_id: int, device_index: int):
        self.stop_camera(logical_id)
        cam_thread = CameraThread(device_index)
        cam_thread.ImageUpdate.connect(lambda img, idx=logical_id: self.opencv_emit(img, idx))
        self.camera_threads[logical_id] = cam_thread
        cam_thread.start()
        self.LoadWebcam()

    def StartWebCam(self):
        logic_id = self.pick_cam.currentIndex()
        device_index = self.camlist.currentIndex()
        self.start_camera(logic_id, device_index)

    def stop_camera(self, logical_id: int):
        thread = self.camera_threads.get(logical_id)
        if thread:
            thread.stop()
            self.camera_threads[logical_id] = None

    def cvt_cv_qt(self, Image):
        rgb_image = cv2.cvtColor(Image, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_image.shape
        bytes_per_line = ch * w
        qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
        return QPixmap.fromImage(qt_image)

    def process_cam_out_image(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    def process_cam_in_image(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    @pyqtSlot(np.ndarray)
    def opencv_emit(self, Image, logical_cam):
        if Image is None:
            return
        if logical_cam == 0:
            processed = self.process_cam_in_image(Image)
            self.disp_main_in.setPixmap(self.cvt_cv_qt(processed))
        elif logical_cam == 1:
            processed = self.process_cam_in_image(Image)
            self.disp_main_out.setPixmap(self.cvt_cv_qt(processed))
        elif logical_cam == 2:
            self.latest_check_frame = Image.copy()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
