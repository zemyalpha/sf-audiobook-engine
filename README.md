# SF Audiobook Engine

드라마 스타일 오디오북 자동 생성 시스템. SF 소설을 분석하여 캐릭터별 음성 캐스팅, 감정 연기를 적용한 오디오북을 자동으로 만듭니다.

## 기능

- **캐릭터 분석**: 소설 텍스트에서 캐릭터, 화자, 감정을 자동 추출
- **음성 캐스팅**: 캐릭터 성격/나이/성별에 따라 최적의 음성 할당
- **감정 연기**: 8가지 감정 태그(calm/angry/sad/tense/happy/fear/whisper/narration)에 따라 rate/pitch/volume 미세 조정
- **씬 구분 처리**: 장면 전환 시 정적 구간 자동 삽입
- **MP3 + M4B 출력**: 범용 MP3와 오디오북 포맷 M4B 동시 생성
- **웹 플레이어**: 재생 속도 조절, 진행 바, 탐색 기능이 있는 플레이어

## 기술 스택

| 구성 요소 | 기술 |
|-----------|------|
| TTS 엔진 | Microsoft Edge-TTS (Neural, 무료) |
| 오디오 처리 | FFmpeg |
| 텍스트 분석 | GLM-5.2 (LLM) 또는 규칙 기반 fallback |
| 음성 | ko-KR-SunHiNeural (여), ko-KR-HyunsuMultilingualNeural (남), ko-KR-InJoonNeural (서술자) |

## 사용법

```bash
# 기본
python3 audiobook/engine.py \
  --story public/stories/the-weight-of-memory.html \
  --title "기억의 무게" \
  --output output/weight-of-memory

# 미리 분석된 대본 사용 (LLM 호출 생략)
python3 audiobook/engine.py \
  --story public/stories/the-weight-of-memory.html \
  --title "기억의 무게" \
  --output output/weight-of-memory \
  --script-json output/weight-of-memory/script.json
```

## 음성 프로필 시스템

각 캐릭터는 기본 음성 프로필을 가지며, 감정 상태에 따라 동적으로 조정됩니다:

```
서연 (기본)     → ko-KR-SunHiNeural,     rate +0%,  pitch +3Hz
서연 (감정)     → 동일 음성,              rate -5%,  pitch +8Hz, volume +5%
민준 (기본)     → ko-KR-HyunsuMultilingual, rate -3%, pitch -5Hz
민준 (분노)     → 동일 음성,              rate +8%,  pitch +5Hz, volume +10%
민준 (슬픔)     → 동일 음성,              rate -12%, pitch -10Hz, volume -5%
서술자          → ko-KR-InJoonNeural,     rate -5%,  pitch -2Hz
```

## 파이프라인

```
소설 HTML
  ↓ 텍스트 추출
순수 텍스트
  ↓ LLM 분석 (또는 규칙 기반 fallback)
대본 JSON (화자/감정/텍스트)
  ↓ 음성 프로필 매핑 + 감정 조정
개별 음성 세그먼트 (edge-tts)
  + 정적 구간 삽입 (ffmpeg)
  ↓ 연결
최종 MP3 + M4B
```

## 첫 작품: 「기억의 무게」

- **장르**: 근미래 SF 단편
- **주제**: 기억 복제 시대의 정체성과 공감
- **분량**: 14분 28초, 83개 세그먼트
- **기술 근거**: Neuralink BCI, UC Berkeley 기억 재구성 연구, MIT 해마 인코딩 연구

## 프로젝트 구조

```
sf-novel-engine/
├── audiobook/
│   └── engine.py          # 오디오북 생성 엔진
├── public/
│   ├── index.html         # 작품 목록 페이지
│   ├── stories/
│   │   └── the-weight-of-memory.html   # 소설
│   ├── audiobook/
│   │   └── the-weight-of-memory.html   # 오디오북 플레이어
│   └── audio/
│       ├── weight-of-memory.mp3        # 최종 오디오
│       ├── weight-of-memory.m4b        # 오디오북 포맷
│       └── weight-of-memory-script.json # 분석된 대본
├── output/                # 생성 산출물
└── README.md
```

## 향후 계획

- [ ] LLM 기반 정밀 대사 분석 (fallback 개선)
- [ ] 다국어 음성 지원
- [ ] 배경음악/효과음 자동 삽입
- [ ] 연재물(장편) 자동 오디오북화
- [ ] 음성 감정 분석 피드백 루프

## 라이선스

MIT
