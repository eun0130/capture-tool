# 화면 녹화 1단계 — 구현 계획 (2026-11-12)

제안·목업: `docs/superpowers/specs/2026-11-08-screen-recording/README.md`.

## 결정 (사용자, 2026-11-12)

- **소리 포함**: 마이크와 컴퓨터 소리를 각각 켜고 끔. 둘 다 켜면 한 트랙으로 섞음.
- 기본 형식 **MP4(H.264 + AAC)**, GIF도 고를 수 있음. 단축키 **Ctrl + Alt + R**. 설치 파일이 커져도 됨.
- **집용만** 먼저(회사용은 회사 보안 정책 확인 뒤 — `EXCLUDED_AT_WORK` 에 `record`).
- **인코더는 OS 기본 기능**: GPL 부품 없음. PyAV/FFmpeg 휠은 libx264(GPL)를 품고 있어 쓰지 않는다.
  - Windows: Media Foundation **Sink Writer**(H.264 + AAC → MP4), comtypes 로(이미 dxcam 이 가져옴).
  - 맥: **AVAssetWriter**(H.264 + AAC → MP4), pyobjc.
- 소리 받기: Windows `soundcard`(BSD, WASAPI — 마이크와 스피커 루프백), 맥 마이크 `soundcard`(CoreAudio),
  맥 컴퓨터 소리 **ScreenCaptureKit**(macOS 13+; 화면 기록 권한).

## 구조

```
core/recording.py        RecordingSession: 초당 장면 수에 맞춰 영역 grab → writer, 일시정지, 최대 길이, 통계,
                         소리 섞기(48 kHz 스테레오 float32), 녹화 중 소리 WAV 따로 보관(자르기용)
core/recording_export.py 자르기(앞뒤) → MP4 다시 쓰기, GIF(Pillow) — 영상 읽기는 cv2.VideoCapture
platform/<os> recorder   open_writer(path, w, h, fps, audio) → add_frame / add_audio / close
platform/<os> audio      sources(): 마이크·컴퓨터 소리 → 블록 콜백
app/recording_ui.py      영역 테두리 + 조작 막대(시간·크기·마이크·소리·일시정지·끝내기(Esc)) + 3초 세기
app/recording_result.py  결과 창: 미리 보기·재생, 앞뒤 자르기, MP4/GIF·화질, 예상 크기, 복사(파일)·저장·메일·카톡·폴더·다시 녹화
```
영상 원본은 녹화하는 동안 바로 인코딩(메모리에 쌓지 않음). 자르지 않으면 그 파일을 그대로 쓴다.

## 작업 (각각 테스트 먼저 → 구현 → 커밋)

1. `core/recording.py` — 타이밍·일시정지·끝·최대 길이·누락 장면 수·소리 섞기 (가짜 grab/writer/시계로 단위 테스트)
2. 맥 writer (AVAssetWriter) — 실제 2초 영상+소리 → cv2 로 읽어 장면 수·크기, AVAsset 으로 길이·소리 트랙 확인
3. Windows writer (Media Foundation) — 단위 테스트(가짜 COM) + Windows 실제 테스트(사용자 PC, GitHub 서버에는 Media Foundation 없음)
4. 소리 받기 — 섞기·리샘플은 단위, 실제 장치는 맥(권한 있으면)·Windows 실제 테스트
5. 내보내기 — 자르기 MP4, GIF(크기·장면 수)
6. 화면 — 막대 녹화 버튼·단축키 슬롯·녹화 중 화면·결과 창·설정 칸·Esc(키보드가 다른 앱에 있어도)·회사용 제외
7. 클립보드에 파일로 복사(Windows CF_HDROP, 맥 파일 URL)
8. 패키징 — 숨은 import, 맥 Info.plist 마이크 권한 문구, `--check-backend` 가 녹화 부품 확인
9. 문서 — 안내 페이지·USER_GUIDE·QUICK_START·릴리스 노트·test-cases, 목업을 실제 화면으로 교체
