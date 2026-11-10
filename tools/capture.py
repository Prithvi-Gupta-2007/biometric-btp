"""Optional helper: capture a face image from the webcam (needs: pip install opencv-python).
If Part A already produces a file (image / fingerprint template), skip this and pass it to btp.client --file."""
import argparse
import os
import sys
import time

try:
    import cv2
except ImportError:
    sys.exit("opencv-python not installed: pip install opencv-python  (or use your Part A file directly)")

ap = argparse.ArgumentParser()
ap.add_argument("--camera", type=int, default=0)
ap.add_argument("--out", default="captured")
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
cap = cv2.VideoCapture(a.camera)
print("Press SPACE to capture, ESC to quit")
while True:
    ok, frame = cap.read()
    if not ok:
        sys.exit("camera read failed")
    cv2.imshow("capture", frame)
    k = cv2.waitKey(1) & 0xFF
    if k == 27:
        break
    if k == 32:
        path = os.path.join(a.out, f"face_{time.strftime('%Y%m%d-%H%M%S')}.jpg")
        cv2.imwrite(path, frame)
        print("saved", path)
        break
cap.release()
cv2.destroyAllWindows()
