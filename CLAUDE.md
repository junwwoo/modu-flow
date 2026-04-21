# ModuFlow Project

## Overview

MediaPipe PoseLandmarker를 활용한 실시간 포즈 추정 프로젝트.
웹캠 영상에서 인체 관절을 감지하고 각도를 계산하여 시각화한다.
추후에 모바일 안드로이드 환경으로 변경하고 운동 자세 분석과
자세 피드백을 시각화하는 기능을 제공한다.

## Project Structure

```
moduflow_project/
└── ai_pose_project/
    ├── pose_landmarker_lite.task   # MediaPipe 모델 파일
    ├── venv/                       # Python 가상환경
    └── src/
        ├── test_pose.py            # 기본 랜드마크 표시
        ├── test_pose_2.py          # 주요 관절 좌표 출력
        ├── test_pose_3.py          # 관절 각도 계산 + 화면 표시
        ├── test_pose_4.py          # 스쿼트 자세 판별 + 횟수 카운팅
        ├── test_pose_5.py          # 자세 교정 피드백 메시지
        └── test_pose_6.py          # 데이터 구조 설계 (좌표/각도 저장)
```

## Tech Stack

- Python
- OpenCV (`cv2`)
- MediaPipe (PoseLandmarker, Tasks API)
- NumPy

## Development

- 가상환경: `ai_pose_project/venv/`
- 모델: `pose_landmarker_lite.task` (MediaPipe Pose Landmarker Lite)
- 실행: `ai_pose_project/src/` 디렉토리에서 스크립트 실행 (모델 경로가 상대경로)

## Conventions

- 언어: 한국어 주석 사용
- ESC 키로 프로그램 종료
- BGR → RGB 변환 후 MediaPipe에 전달
