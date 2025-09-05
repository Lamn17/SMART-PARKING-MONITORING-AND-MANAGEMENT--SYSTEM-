import cv2
import torch
import function.utils_rotate as utils_rotate
import function.helper as helper
import pathlib
from pathlib import Path
pathlib.PosixPath = pathlib.WindowsPath

# Load model toàn cục (tùy bạn tối ưu hoá)


yolo_LP_detect = torch.hub.load('yolov5', 'custom', "best .pt", force_reload=True, source='local')
# yolo_LP_detect = torch.hub.load('yolov5', 'custom', path='model/LP_detector.pt', force_reload=False, source='local')
yolo_license_plate = torch.hub.load('yolov5', 'custom', path='model/LP_ocr_nano_62.pt', force_reload=False, source='local')
yolo_license_plate.conf = 0.5

def detect_plate_and_compare(frame):
    plates = yolo_LP_detect(frame, size=640)
    list_plates = plates.pandas().xyxy[0].values.tolist()
    list_read_plates = set()

    for plate in list_plates:
        flag = 0
        x = int(plate[0])
        y = int(plate[1])
        w = int(plate[2] - plate[0])
        h = int(plate[3] - plate[1])
        crop_img = frame[y:y + h, x:x + w]
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 0, 225), 2)

        for cc in range(0, 2):
            for ct in range(0, 2):
                deskewed = utils_rotate.deskew(crop_img, cc, ct)
                lp = helper.read_plate(yolo_license_plate, deskewed)
                if lp != "unknown":
                    list_read_plates.add(lp)
                    cv2.putText(frame, lp, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (36, 255, 12), 2)
                    flag = 1
                    break
            if flag:
                break

    return list_read_plates, frame
