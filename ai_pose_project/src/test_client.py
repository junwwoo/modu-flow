"""
pose_server REST + WebSocket 통합 테스트 클라이언트.

전제: pose_server가 http://127.0.0.1:8000 에서 실행 중이어야 함.
  uvicorn pose_server:app --host 127.0.0.1 --port 8000
"""
import asyncio
import base64
import json
import os

import requests
import websockets

HERE     = os.path.dirname(os.path.abspath(__file__))
TEST_DIR = os.path.normpath(os.path.join(HERE, "..", "test_images"))
SERVER   = "http://127.0.0.1:8000"
WS_URL   = "ws://127.0.0.1:8000/ws"


def list_images():
    return sorted(
        f for f in os.listdir(TEST_DIR)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
        and not f.startswith("_")
    )


def encode_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def test_health():
    print("=" * 70)
    print("HEALTH CHECK")
    print("=" * 70)
    r = requests.get(f"{SERVER}/health", timeout=5)
    print(f"GET /health  →  HTTP {r.status_code}  {r.json()}")


def test_rest():
    print("\n" + "=" * 70)
    print("REST 테스트: POST /analyze")
    print("=" * 70)

    for f in list_images():
        path = os.path.join(TEST_DIR, f)
        b64  = encode_b64(path)
        try:
            r = requests.post(
                f"{SERVER}/analyze",
                json={"image": b64},
                timeout=30,
            )
            print(f"\n[{f}]  HTTP {r.status_code}")
            if r.status_code == 200:
                body = r.json()
                print(f"  posture : {body['posture']}")
                print(f"  feedback: {body['feedback']}")
                print(f"  angles  : {body['angles']}")
            else:
                print(f"  body: {r.text}")
        except Exception as e:
            print(f"[{f}] ERROR: {e}")

    # 에러 케이스: 잘못된 base64
    print("\n[잘못된 base64]")
    r = requests.post(f"{SERVER}/analyze",
                      json={"image": "!!!not_base64"}, timeout=10)
    print(f"  HTTP {r.status_code}  {r.text}")

    # 에러 케이스: 빈 image 필드
    print("\n[빈 image 필드]")
    r = requests.post(f"{SERVER}/analyze",
                      json={"image": ""}, timeout=10)
    print(f"  HTTP {r.status_code}  {r.text}")


async def test_websocket():
    print("\n" + "=" * 70)
    print("WebSocket 테스트: /ws")
    print("=" * 70)

    files = list_images()
    async with websockets.connect(WS_URL) as ws:
        # 1) 정상 케이스: 여러 프레임 연속 전송
        for f in files:
            path = os.path.join(TEST_DIR, f)
            b64  = encode_b64(path)
            await ws.send(json.dumps({"type": "frame", "image": b64}))
            data = json.loads(await ws.recv())
            print(f"\n[{f}]")
            print(f"  type    : {data['type']}")
            if data["type"] == "result":
                print(f"  posture : {data['posture']}")
                print(f"  feedback: {data['feedback']}")
                print(f"  angles  : {data['angles']}")
            else:
                print(f"  message : {data.get('message')}")

        # 2) 에러: 지원하지 않는 type
        print("\n[지원하지 않는 type]")
        await ws.send(json.dumps({"type": "wrong", "image": ""}))
        print(f"  {await ws.recv()}")

        # 3) 에러: 잘못된 base64
        print("\n[잘못된 base64]")
        await ws.send(json.dumps({"type": "frame", "image": "!!!not_base64"}))
        print(f"  {await ws.recv()}")

        # 4) 연결 유지 검증: 에러 직후에도 정상 메시지 처리되는가
        print("\n[연결 유지 검증: 에러 후 정상 요청]")
        b64 = encode_b64(os.path.join(TEST_DIR, files[0]))
        await ws.send(json.dumps({"type": "frame", "image": b64}))
        data = json.loads(await ws.recv())
        print(f"  type={data['type']}  posture={data.get('posture')}  → 연결 유지 OK")


def main():
    test_health()
    test_rest()
    asyncio.run(test_websocket())
    print("\n" + "=" * 70)
    print("[DONE] 모든 테스트 완료")
    print("=" * 70)


if __name__ == "__main__":
    main()
