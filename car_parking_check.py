# car_parking_check.py
import torch
import pathlib
import json
import numpy as np
import cv2

# Fix pathlib on Windows
pathlib.PosixPath = pathlib.WindowsPath

# Load YOLOv5 model
model = torch.hub.load('yolov5', 'custom', "car_detect.pt", force_reload=True, source='local')
model.conf = 0.7
vehicle_classes = ['car']

# Load vùng đỗ
with open("parking_slots.json", "r") as f:
    parking_boxes = json.load(f)

def is_vehicle_in_slot(vehicle_box, slot_box, threshold=0.2):
    vx1, vy1, vx2, vy2 = vehicle_box
    sx1, sy1, sx2, sy2 = slot_box
    ix1 = max(vx1, sx1)
    iy1 = max(vy1, sy1)
    ix2 = min(vx2, sx2)
    iy2 = min(vy2, sy2)
    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)
    inter_area = iw * ih
    slot_area = (sx2 - sx1) * (sy2 - sy1)
    return (inter_area / slot_area) > threshold

def check_parking_occupancy(frame):
    frame = cv2.resize(frame, (640, 480))

    """
    Nhận ảnh đầu vào (BGR), trả về:
    - annotated frame (có box vẽ)
    - danh sách slot: [{'slot': i, 'status': 'Occupied'/'Empty'}]
    """
    results = model(frame)
    detections = results.xyxy[0].cpu().numpy()
    names = model.names
    empty_slots = []  # danh sách slot trống
    vehicle_boxes = []
    for det in detections:
        x1, y1, x2, y2, conf, cls_id = det
        cls_name = names[int(cls_id)]
        if cls_name in vehicle_classes:
            vehicle_boxes.append((int(x1), int(y1), int(x2), int(y2)))
            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (255, 255, 0), 2)
            cv2.putText(frame, cls_name, (int(x1), int(y1) - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

    results = []
    
    for idx, box in enumerate(parking_boxes):
        sx1, sy1, sx2, sy2 = box["x1"], box["y1"], box["x2"], box["y2"]
        slot = (sx1, sy1, sx2, sy2)

        occupied = any(is_vehicle_in_slot(vb, slot) for vb in vehicle_boxes)
        color = (0, 0, 255) if occupied else (0, 255, 0)
        label = "Occupied" if occupied else "Empty"

        # Gán mã tên slot
        if idx < 3:
            slot_name = f"A{idx + 1}"
        else:
            slot_name = f"B{idx - 2}"

        # Vẽ box và nhãn
        cv2.rectangle(frame, (sx1, sy1), (sx2, sy2), color, 2)
        cv2.putText(frame, f"{slot_name} - {label}", (sx1, sy1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

        results.append({"slot": slot_name, "status": label})

        if not occupied:
            empty_slots.append(slot_name)

    return frame, results, empty_slots
