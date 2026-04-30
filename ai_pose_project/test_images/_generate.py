"""
analyze_pose 모듈 테스트용 더미 이미지 생성기.

생성 이미지:
  - blank_black.jpg   : 검은 단색         → "Person not detected" 케이스
  - noise.jpg         : 랜덤 노이즈        → "Person not detected" 케이스
  - stick_figure.jpg  : 간단한 스틱 피규어 → MediaPipe가 인식할 수도/안 할 수도 (경계 케이스)

실제 사람 사진을 같은 디렉토리에 추가하면 정상 분석(posture/angles) 케이스도 함께 검증할 수 있다.
"""
import os
import numpy as np
from PIL import Image, ImageDraw

OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def make_blank_black():
    img = Image.new("RGB", (640, 480), color=(0, 0, 0))
    img.save(os.path.join(OUT_DIR, "blank_black.jpg"), quality=85)


def make_noise():
    arr = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
    Image.fromarray(arr).save(os.path.join(OUT_DIR, "noise.jpg"), quality=85)


def make_stick_figure():
    img = Image.new("RGB", (640, 480), color=(230, 230, 230))
    d = ImageDraw.Draw(img)
    # 머리
    d.ellipse((300, 70, 340, 115), outline=(0, 0, 0), width=3)
    # 몸통
    d.line((320, 115, 320, 280), fill=(0, 0, 0), width=3)
    # 양 팔
    d.line((320, 160, 240, 240), fill=(0, 0, 0), width=3)
    d.line((320, 160, 400, 240), fill=(0, 0, 0), width=3)
    # 양 다리
    d.line((320, 280, 270, 410), fill=(0, 0, 0), width=3)
    d.line((320, 280, 370, 410), fill=(0, 0, 0), width=3)
    img.save(os.path.join(OUT_DIR, "stick_figure.jpg"), quality=85)


if __name__ == "__main__":
    make_blank_black()
    make_noise()
    make_stick_figure()
    for f in sorted(os.listdir(OUT_DIR)):
        if f.endswith(".jpg"):
            size = os.path.getsize(os.path.join(OUT_DIR, f))
            print(f"  {f:20s}  {size:>8} bytes")
    print(f"\n[OK] 출력 디렉토리: {OUT_DIR}")
