# raw_videos — 운동 원본 영상 (프레임 추출용 입력)

팀원이 촬영한 **운동 원본 영상**을 여기에 넣는다. 이 영상에서 `_extract.py`가
프레임을 골라 `test_images/<운동>/<라벨>/`에 저장해 데이터셋을 만든다.

> ⚠️ **영상 파일은 저장소에 커밋되지 않는다**(`.gitignore`). 용량이 크고, 프레임을
> 추출하고 나면 더 이상 필요 없기 때문. 이 README 와 폴더 구조만 git 에 남는다.
> (실제 데이터셋 = 추출된 프레임은 `test_images/`에 커밋된다.)

## 영상 넣는 법

1. 촬영 가이드(`../docs/capture_guide_w14.md`)대로 **영상 1개 = 한 동작**으로 촬영.
2. 파일명: `<멤버>_<운동>_<라벨>_<각도>.mp4`
   - 멤버: `m1`(박준우) `m2`(이경민) `m3`(임용완) `m4`(정주영)
   - 운동: `squat` `lunge` `pushup` `lateralraise` `shoulderpress` `pullup` `situp`
   - 라벨: `good` `trunk_lean` `knee_forward` `asymmetry` `arms_too_high` `hip_sag` ...
   - 각도: `side` 또는 `front`
   - 예) `m2_squat_trunk_lean_side.mp4`, `m3_lateralraise_asymmetry_front.mp4`
3. 이 폴더에 넣고 담당자(박준우)에게 알린다.

## 추출 (담당자)

```bash
# 예: 상체 숙인 스쿼트 영상 → trunk_lean 프레임 추출
python ../test_images/_extract.py raw_videos/m2_squat_trunk_lean_side.mp4 \
       --exercise squat --label trunk_lean --view side --member m2

# 정상 영상은 두 번 돌려 good_up / good_down 둘 다 추출
python ../test_images/_extract.py raw_videos/m2_squat_good_side.mp4 \
       --exercise squat --label good_down --view side --member m2
python ../test_images/_extract.py raw_videos/m2_squat_good_side.mp4 \
       --exercise squat --label good_up --view side --member m2
```

추출 후 `python src/test_dataset.py`로 라벨별 정확도를 확인하고 임계값을 튜닝한다.
