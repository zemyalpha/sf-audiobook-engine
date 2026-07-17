"""
SF Audiobook Engine - 드라마 오디오북 생성 시스템
캐릭터 분석 → 감정 추출 → 캐릭터별 음성 매핑 → 오디오 생성
"""
import asyncio
import json
import os
import re
import subprocess
import tempfile
import argparse
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

try:
    import edge_tts
except ImportError:
    edge_tts = None

# ============================================================
# 캐릭터 음성 매핑
# ============================================================
DEFAULT_VOICE_MAP = {
    "narrator": {
        "voice": "ko-KR-InJoonNeural",
        "rate": "-5%",
        "pitch": "-2Hz",
        "volume": "+0%",
        "desc": "객관적이고 차분한 3인칭 서술자"
    },
    "seo_yeon": {
        "voice": "ko-KR-SunHiNeural",
        "rate": "+0%",
        "pitch": "+3Hz",
        "volume": "+0%",
        "desc": "여성 20대후반. 호기심 많고 감수성 풍부. 약간 높은 톤."
    },
    "min_jun": {
        "voice": "ko-KR-HyunsuMultilingualNeural",
        "rate": "-3%",
        "pitch": "-5Hz",
        "volume": "+0%",
        "desc": "남성 30대초반. 감정을 숨기는 성격. 낮고 묵직한 톤."
    },
    "min_jun_angry": {
        "voice": "ko-KR-HyunsuMultilingualNeural",
        "rate": "+8%",
        "pitch": "+5Hz",
        "volume": "+10%",
        "desc": "민준 - 분노/긴장 상태. 빠르고 높은 톤."
    },
    "min_jun_sad": {
        "voice": "ko-KR-HyunsuMultilingualNeural",
        "rate": "-12%",
        "pitch": "-10Hz",
        "volume": "-5%",
        "desc": "민준 - 슬픔/무기력. 느리고 낮은 톤."
    },
    "seo_yeon_emotional": {
        "voice": "ko-KR-SunHiNeural",
        "rate": "-5%",
        "pitch": "+8Hz",
        "volume": "+5%",
        "desc": "서연 - 감정 격해진 상태. 떨리는 듯한 톤."
    },
    "system": {
        "voice": "ko-KR-InJoonNeural",
        "rate": "+0%",
        "pitch": "-15Hz",
        "volume": "-10%",
        "desc": "시스템 메시지/계약서/약관. 기계적이고 무미건조."
    },
    "internal": {
        "voice": "ko-KR-SunHiNeural",
        "rate": "-8%",
        "pitch": "+1Hz",
        "volume": "-15%",
        "desc": "내면 독백. 속삭이듯 조용한 톤."
    },
}

# 감정→음성 매핑 우선순위
EMOTION_VOICE_OVERRIDE = {
    "angry": {"rate_delta": "+12%", "pitch_delta": "+8Hz", "volume_delta": "+10%"},
    "sad": {"rate_delta": "-10%", "pitch_delta": "-8Hz", "volume_delta": "-5%"},
    "fear": {"rate_delta": "+5%", "pitch_delta": "+3Hz", "volume_delta": "-5%"},
    "happy": {"rate_delta": "+5%", "pitch_delta": "+5Hz", "volume_delta": "+0%"},
    "tense": {"rate_delta": "+8%", "pitch_delta": "+2Hz", "volume_delta": "+5%"},
    "calm": {"rate_delta": "-5%", "pitch_delta": "+0Hz", "volume_delta": "+0%"},
    "whisper": {"rate_delta": "-15%", "pitch_delta": "-3Hz", "volume_delta": "-20%"},
    "narration": {"rate_delta": "-3%", "pitch_delta": "-2Hz", "volume_delta": "+0%"},
}


@dataclass
class DialogueLine:
    """대사/서술 한 줄"""
    speaker: str          # seo_yeon, min_jun, narrator, system, internal
    emotion: str          # calm, angry, sad, tense, happy, fear, whisper, narration
    text: str             # 실제 텍스트
    voice_profile: str    # 적용할 음성 프로필 키
    line_num: int = 0     # 줄 번호


@dataclass
class Character:
    """캐릭터 정의"""
    name: str
    display_name: str
    gender: str
    age: str
    personality: str
    voice_desc: str
    voice_profile: str    # DEFAULT_VOICE_MAP 키


@dataclass
class AudiobookConfig:
    """오디오북 생성 설정"""
    title: str = ""
    author: str = "SF Novel Engine"
    story_file: str = ""
    output_dir: str = ""
    sample_rate: int = 24000
    gap_between_lines: float = 0.4        # 줄 간 정적 시간 (초)
    gap_scene_break: float = 1.5          # 씬 구분 정적 시간
    gap_paragraph: float = 0.8            # 단락 간 정적
    generate_m4b: bool = True             # m4b (단일 파일) 생성 여부
    chapters_json: str = ""               # 미리 분석된 JSON 경로 (있으면 LLM 호출 생략)


# ============================================================
# 소설 분석 (LLM 사용)
# ============================================================

STORY_ANALYSIS_PROMPT = """당신은 SF 소설을 드라마 오디오북으로 제작하기 위한 대본 분석가입니다.
주어진 소설 텍스트를 분석하여, 각 문장/단락을 화자와 감정이 태깅된 대본으로 변환하세요.

## 캐릭터 정의
- 서연(seo_yeon): 여성, 20대후반, 호기심 많고 감수성 풍부
- 민준(min_jun): 남성, 30대초반, 감정을 숨기는 성격
- 서술자(narrator): 3인칭 객관적 서술
- 시스템(system): 계약서, 약관, 시스템 메시지 등
- 내면(internal): 인물의 내면 독백/생각

## 감정 태그
calm, angry, sad, tense, happy, fear, whisper, narration

## 규칙
1. 각 줄은 하나의 화자와 감정을 가진다
2. 대사는 따옴표 안의 내용, 서술은 그 외
3. "~~생각했다" / 이탤릭체(·) / 괄호 안의 내용은 internal 화자
4. 감정이 바뀌면 같은 화자라도 줄을 나눈다
5. 씬 구분(· · ·)은 별도 줄로 {scene_break: true} 태그
6. 각 줄은 가능한 자연스러운 단위(1~3문장)로 나눈다

## 출력 형식 (JSON)
```json
{
  "characters": [
    {"name": "seo_yeon", "display_name": "서연", "gender": "female", "age": "20대후반", "personality": "호기심 많고 감수성 풍부", "voice_desc": "맑고 약간 높은 톤, 감정이 잘 드러남", "voice_profile": "seo_yeon"}
  ],
  "script": [
    {"speaker": "narrator", "emotion": "narration", "text": "서연은 처음 남편의 기억을 재생했을 때, 0.7초의 침침을 들었다."},
    {"speaker": "narrator", "emotion": "narration", "text": "화면이 아니었다..."},
    {"scene_break": true},
    {"speaker": "min_jun", "emotion": "angry", "text": "너, 내 기억을 다 봤어?"},
    {"speaker": "seo_yeon", "emotion": "tense", "text": "...일부만."},
    {"speaker": "internal", "emotion": "whisper", "text": "이건 내 고통이 아닌데."}
  ]
}
```

## 소설 텍스트:
{story_text}

위 텍스트를 분석하여 JSON 형식으로 출력하세요. JSON 블록만 출력하고 다른 설명은 하지 마세요."""


async def analyze_story_with_llm(story_text: str, config_path: str = "~/.hermes/config.yaml") -> dict:
    """GLM-5.2를 사용해 소설을 분석하여 대본으로 변환"""
    import subprocess
    
    # 긴 텍스트는 청크로 분할
    MAX_CHARS = 6000
    if len(story_text) <= MAX_CHARS:
        chunks = [story_text]
    else:
        # 문단 단위로 분할
        paragraphs = story_text.split('\n')
        chunks = []
        current = ""
        for p in paragraphs:
            if len(current) + len(p) > MAX_CHARS:
                if current:
                    chunks.append(current)
                current = p + "\n"
            else:
                current += p + "\n"
        if current:
            chunks.append(current)
    
    print(f"[분석] 소설을 {len(chunks)}개 청크로 분할하여 분석합니다...")
    
    all_script = []
    characters_set = {}
    
    for i, chunk in enumerate(chunks):
        prompt = STORY_ANALYSIS_PROMPT.replace("{story_text}", chunk)
        
        # Hermes CLI로 GLM 호출
        result = subprocess.run(
            ["hermes", "prompt", "--model", "zai/glm-5.2", "--no-tools", prompt],
            capture_output=True, text=True, timeout=180,
            env={**os.environ, "HERMES_PROMPT_SIZE_WARN": "0"}
        )
        
        if result.returncode != 0:
            print(f"[경고] 청크 {i+1} LLM 분석 실패, fallback 사용")
            fallback = manual_script_chunk(chunk)
            all_script.extend(fallback["script"])
            continue
        
        # JSON 추출
        output = result.stdout.strip()
        json_match = re.search(r'\{[\s\S]*\}', output)
        if json_match:
            try:
                data = json.loads(json_match.group())
                if "script" in data:
                    all_script.extend(data["script"])
                if "characters" in data:
                    for c in data["characters"]:
                        characters_set[c["name"]] = c
                print(f"  [청크 {i+1}] {len(data.get('script', []))}줄 추출")
            except json.JSONDecodeError:
                print(f"  [청크 {i+1}] JSON 파싱 실패, fallback 사용")
                fallback = manual_script_chunk(chunk)
                all_script.extend(fallback["script"])
    
    return {
        "characters": list(characters_set.values()) if characters_set else [
            {"name": "seo_yeon", "display_name": "서연", "gender": "female", "age": "20대후반", 
             "personality": "호기심 많고 감수성 풍부", "voice_desc": "맑고 약간 높은 톤", "voice_profile": "seo_yeon"},
            {"name": "min_jun", "display_name": "민준", "gender": "male", "age": "30대초반",
             "personality": "감정을 숨기는 성격", "voice_desc": "낮고 묵직한 톤", "voice_profile": "min_jun"},
        ],
        "script": all_script
    }


def manual_script_chunk(text: str) -> dict:
    """LLM 없이 규칙 기반으로 대본 분석 (fallback)"""
    script = []
    lines = text.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if '· · ·' in line:
            script.append({"scene_break": True})
            continue
        
        # 대사 추출 (따옴표 안)
        dialogue_match = re.findall(r'[""\'\'](.+?)[""\'\']', line)
        narration_part = line
        
        if dialogue_match:
            for d in dialogue_match:
                # 대사 앞 서술부
                idx = narration_part.find(d)
                if idx > 0:
                    before = narration_part[:idx].strip()
                    before = before.strip('"').strip("'").strip('\u201c').strip('\u201d').strip()
                    if before:
                        # 서술부에서 화자 추정
                        speaker, emotion = guess_speaker_emotion(before)
                        script.append({"speaker": speaker, "emotion": emotion, "text": before})
                
                speaker, emotion = guess_speaker_emotion(d)
                script.append({"speaker": speaker, "emotion": emotion, "text": d})
                narration_part = narration_part[idx + len(d):]
            
            # 남은 서술부
            remaining = narration_part.strip()
            remaining = remaining.strip('"').strip("'").strip('\u201c').strip('\u201d').strip()
            if remaining:
                speaker, emotion = guess_speaker_emotion(remaining)
                script.append({"speaker": speaker, "emotion": emotion, "text": remaining})
        else:
            # 내면 독백 (이탤릭)
            if line.startswith('<em>') or '<em>' in line:
                clean = re.sub(r'</?em>', '', line).strip()
                script.append({"speaker": "internal", "emotion": "whisper", "text": clean})
            # 굵은 글씨 (강조/시스템)
            elif '<strong>' in line or line.startswith('**'):
                clean = re.sub(r'</?strong>|\*\*', '', line).strip()
                if '조항' in line or '약관' in line or '이용자' in line:
                    script.append({"speaker": "system", "emotion": "narration", "text": clean})
                else:
                    script.append({"speaker": "narrator", "emotion": "tense", "text": clean})
            else:
                script.append({"speaker": "narrator", "emotion": "narration", "text": line})
    
    return {"script": script}


def guess_speaker_emotion(text: str) -> tuple:
    """텍스트에서 화자와 감정 추정"""
    if '서연' in text and ('말' in text or '물었' in text or '대답' in text):
        return ("seo_yeon", "calm")
    if '민준' in text and ('말' in text or '물었' in text or '대답' in text):
        return ("min_jun", "calm")
    if any(w in text for w in ['화났', '소리쳤', '날이 서', '굳었', '분노', '격하게']):
        return ("narrator", "tense")
    if any(w in text for w in ['눈물', '슬퍼', '우는', '떨렸', '무기력']):
        return ("narrator", "sad")
    return ("narrator", "narration")


# ============================================================
# 음성 프로필 결정
# ============================================================

def resolve_voice_profile(speaker: str, emotion: str) -> str:
    """화자+감정 → 음성 프로필 키 결정"""
    # 특정 감정 상태의 전용 프로필 확인
    key = f"{speaker}_{emotion}"
    if key in DEFAULT_VOICE_MAP:
        return key
    return speaker if speaker in DEFAULT_VOICE_MAP else "narrator"


def apply_emotion_adjustments(profile: dict, emotion: str) -> dict:
    """감정에 따른 rate/pitch/volume 미세 조정"""
    result = profile.copy()
    if emotion in EMOTION_VOICE_OVERRIDE:
        adj = EMOTION_VOICE_OVERRIDE[emotion]
        result["rate"] = adjust_value(result.get("rate", "+0%"), adj["rate_delta"])
        result["pitch"] = adjust_value(result.get("pitch", "+0Hz"), adj["pitch_delta"])
        result["volume"] = adjust_value(result.get("volume", "+0%"), adj["volume_delta"])
    return result


def adjust_value(base: str, delta: str) -> str:
    """'+5%' + '-3%' = '+2%' 같은 퍼센트/Hz 조정"""
    match = re.match(r'([+-]?)(\d+)(%|Hz)', base)
    if not match:
        return delta
    base_sign = 1 if match.group(1) != '-' else -1
    base_val = int(match.group(2)) * base_sign
    unit = match.group(3)
    
    d_match = re.match(r'([+-]?)(\d+)(%|Hz)', delta)
    if not d_match or d_match.group(3) != unit:
        return base
    
    d_sign = 1 if d_match.group(1) != '-' else -1
    d_val = int(d_match.group(2)) * d_sign
    
    final = base_val + d_val
    return f"{'+' if final >= 0 else ''}{final}{unit}"


# ============================================================
# TTS 생성
# ============================================================

async def generate_speech(text: str, voice_profile_key: str, emotion: str, output_path: str) -> bool:
    """단일 텍스트 → 음성 파일 생성"""
    if edge_tts is None:
        print("[오류] edge-tts가 설치되지 않았습니다.")
        return False
    
    profile = DEFAULT_VOICE_MAP.get(voice_profile_key, DEFAULT_VOICE_MAP["narrator"])
    profile = apply_emotion_adjustments(profile, emotion)
    
    voice = profile["voice"]
    rate = profile.get("rate", "+0%")
    pitch = profile.get("pitch", "+0Hz")
    volume = profile.get("volume", "+0%")
    
    try:
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume)
        await communicate.save(output_path)
        return True
    except Exception as e:
        print(f"[오류] TTS 생성 실패: {e}")
        return False


def add_silence(duration_sec: float, output_path: str, sample_rate: int = 24000):
    """정적 구간 생성"""
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", f"anullsrc=channel_layout=mono:sample_rate={sample_rate}",
        "-t", str(duration_sec),
        "-c:a", "libmp3lame", "-b:a", "64k",
        output_path
    ], capture_output=True, timeout=10)


def concat_audio(files: list, output_path: str):
    """여러 오디오 파일 연결"""
    if not files:
        return
    
    list_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
    for f in files:
        list_file.write(f"file '{os.path.abspath(f)}'\n")
    list_file.close()
    
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_file.name,
        "-c:a", "libmp3lame", "-b:a", "128k",
        output_path
    ], capture_output=True, timeout=120)
    
    os.unlink(list_file.name)


# ============================================================
# 메인 파이프라인
# ============================================================

async def generate_audiobook(config: AudiobookConfig):
    """전체 오디오북 생성 파이프라인"""
    print(f"\n{'='*60}")
    print(f"  SF Audiobook Engine — 드라마 오디오북 생성")
    print(f"{'='*60}")
    print(f"  제목: {config.title}")
    print(f"  소설 파일: {config.story_file}")
    print(f"  출력 디렉토리: {config.output_dir}")
    print(f"{'='*60}\n")
    
    # 1. 소설 텍스트 로드
    story_path = os.path.expanduser(config.story_file)
    with open(story_path, 'r', encoding='utf-8') as f:
        story_html = f.read()
    
    # HTML에서 텍스트 추출
    story_text = extract_story_text(story_html)
    print(f"[1/5] 소설 텍스트 추출: {len(story_text)}자")
    
    # 2. 대본 분석 (LLM 또는 fallback)
    if config.chapters_json and os.path.exists(os.path.expanduser(config.chapters_json)):
        print(f"[2/5] 미리 분석된 대본 로드: {config.chapters_json}")
        with open(os.path.expanduser(config.chapters_json), 'r') as f:
            analysis = json.load(f)
    else:
        print(f"[2/5] LLM으로 대본 분석 중...")
        analysis = await analyze_story_with_llm(story_text)
        
        # 분석 결과 저장
        script_path = os.path.join(config.output_dir, "script.json")
        os.makedirs(config.output_dir, exist_ok=True)
        with open(script_path, 'w', encoding='utf-8') as f:
            json.dump(analysis, f, ensure_ascii=False, indent=2)
        print(f"  대본 저장: {script_path}")
    
    characters = analysis.get("characters", [])
    script = analysis.get("script", [])
    print(f"  캐릭터: {len(characters)}명")
    print(f"  대사/서술 줄: {len(script)}줄")
    
    # 3. 음성 프로필 매핑 출력
    print(f"\n[3/5] 음성 캐스팅:")
    for c in characters:
        profile_key = c.get("voice_profile", "narrator")
        profile = DEFAULT_VOICE_MAP.get(profile_key, {})
        voice_name = profile.get("voice", "?")
        print(f"  {c.get('display_name', c['name']):8s} → {voice_name:40s} ({c.get('voice_desc', '')})")
    
    # 4. 각 줄 TTS 생성
    print(f"\n[4/5] 음성 생성 시작...")
    os.makedirs(config.output_dir, exist_ok=True)
    segments_dir = os.path.join(config.output_dir, "segments")
    os.makedirs(segments_dir, exist_ok=True)
    
    audio_files = []
    line_num = 0
    
    for i, item in enumerate(script):
        if item.get("scene_break"):
            # 씬 구분 정적
            silence_path = os.path.join(segments_dir, f"silence_scene_{i:04d}.mp3")
            add_silence(config.gap_scene_break, silence_path)
            audio_files.append(silence_path)
            print(f"  [{i+1:3d}/{len(script)}] --- 씬 구분 ---")
            continue
        
        speaker = item.get("speaker", "narrator")
        emotion = item.get("emotion", "narration")
        text = item.get("text", "").strip()
        
        if not text:
            continue
        
        voice_profile_key = resolve_voice_profile(speaker, emotion)
        segment_path = os.path.join(segments_dir, f"line_{i:04d}.mp3")
        
        success = await generate_speech(text, voice_profile_key, emotion, segment_path)
        if success:
            audio_files.append(segment_path)
            
            # 줄 간 정적
            silence_path = os.path.join(segments_dir, f"silence_{i:04d}.mp3")
            add_silence(config.gap_between_lines, silence_path)
            audio_files.append(silence_path)
            
            preview = text[:40] + "..." if len(text) > 40 else text
            print(f"  [{i+1:3d}/{len(script)}] {speaker:12s} ({emotion:10s}) {preview}")
        else:
            print(f"  [{i+1:3d}/{len(script)}] 실패: {text[:40]}...")
    
    # 5. 오디오 연결
    print(f"\n[5/5] 오디오 연결 중... ({len(audio_files)}개 세그먼트)")
    
    final_mp3 = os.path.join(config.output_dir, f"{config.title}.mp3")
    concat_audio(audio_files, final_mp3)
    
    # m4b 변환 (오디오북 포맷)
    if config.generate_m4b:
        final_m4b = os.path.join(config.output_dir, f"{config.title}.m4b")
        subprocess.run([
            "ffmpeg", "-y", "-i", final_mp3,
            "-c:a", "aac", "-b:a", "96k",
            "-f", "mp4",
            final_m4b
        ], capture_output=True, timeout=120)
        print(f"  M4B 생성: {final_m4b}")
    
    # 파일 크기
    size_mb = os.path.getsize(final_mp3) / (1024 * 1024)
    print(f"\n완료!")
    print(f"  MP3: {final_mp3} ({size_mb:.1f} MB)")
    if config.generate_m4b:
        size_m4b = os.path.getsize(os.path.join(config.output_dir, f"{config.title}.m4b")) / (1024 * 1024)
        print(f"  M4B: {os.path.join(config.output_dir, config.title)}.m4b ({size_m4b:.1f} MB)")
    
    return final_mp3


def extract_story_text(html: str) -> str:
    """HTML에서 소설 본문 텍스트 추출"""
    # <p> 태그 내용만 추출
    paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', html, re.DOTALL)
    lines = []
    for p in paragraphs:
        # HTML 태그 제거
        clean = re.sub(r'<[^>]+>', '', p).strip()
        if clean:
            lines.append(clean)
    return '\n'.join(lines)


# ============================================================
# CLI
# ============================================================

async def main():
    parser = argparse.ArgumentParser(description="SF Audiobook Engine")
    parser.add_argument("--story", required=True, help="소설 HTML 파일 경로")
    parser.add_argument("--title", default="audiobook", help="오디오북 제목")
    parser.add_argument("--output", default="./output", help="출력 디렉토리")
    parser.add_argument("--script-json", default="", help="미리 분석된 대본 JSON (선택)")
    parser_args = parser.parse_args()
    
    config = AudiobookConfig(
        title=parser_args.title,
        story_file=parser_args.story,
        output_dir=parser_args.output,
        chapters_json=parser_args.script_json
    )
    
    await generate_audiobook(config)


if __name__ == "__main__":
    asyncio.run(main())
