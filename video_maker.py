import os, glob, json, asyncio, requests, textwrap
from io import BytesIO
from datetime import datetime
from openai import OpenAI
import edge_tts
from script_templates import fallback_script, normalize_script_payload, split_manual_script
from gtts import gTTS
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from moviepy import ImageClip, AudioFileClip, concatenate_videoclips

VOICE_PROFILES = {
    "Future Leak": ("ko-KR-InJoonNeural", "+12%", "+2Hz"),
    "Money Glitch": ("ko-KR-InJoonNeural", "+12%", "+0Hz"),
    "Secret Vault 24": ("ko-KR-InJoonNeural", "+10%", "-2Hz"),
    "Dark Files Global": ("ko-KR-HyunsuMultilingualNeural", "+8%", "-4Hz"),
    "Unseen Truth": ("ko-KR-HyunsuMultilingualNeural", "+10%", "-2Hz"),
    "Brain Glitch": ("ko-KR-SunHiNeural", "+14%", "+3Hz"),
    "Silent Signals": ("ko-KR-SunHiNeural", "+13%", "+2Hz"),
    "30Sec Shift": ("ko-KR-SunHiNeural", "+14%", "+2Hz"),
    "99% Missed": ("ko-KR-SunHiNeural", "+15%", "+3Hz"),
    "Why Nobody Tells": ("ko-KR-SunHiNeural", "+14%", "+2Hz")
}

async def _synth_edge(text, voice, rate, pitch, out_path):
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    await communicate.save(out_path)

def generate_announcer_audio(text, channel_name, out_path):
    voice, rate, pitch = VOICE_PROFILES.get(channel_name, ("ko-KR-SunHiNeural", "+13%", "+2Hz"))
    try:
        asyncio.run(_synth_edge(text, voice, rate, pitch, out_path))
        if os.path.exists(out_path) and os.path.getsize(out_path) > 500:
            return
    except Exception:
        pass
    gTTS(text=text, lang="ko").save(out_path)

def get_korean_font(size):
    fonts = glob.glob("/usr/share/fonts/**/NanumGothicExtraBold.ttf", recursive=True)
    if not fonts:
        fonts = glob.glob("/usr/share/fonts/**/NanumGothic*.ttf", recursive=True)
    if fonts:
        try:
            return ImageFont.truetype(next(iter(fonts)), size)
        except Exception:
            pass
    return ImageFont.load_default()

def generate_script(channel_name, persona, topic, openai_key):
    if openai_key:
        try:
            client = OpenAI(api_key=openai_key)
            sys_p = f"Channel: {channel_name}, Persona: {persona}. Write 30s Korean Shorts script in 6 short sentences. Return JSON with title, image_prompt, sentences."
            res = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": sys_p}, {"role": "user", "content": topic}],
                response_format={"type": "json_object"}
            )
            data = json.loads(next(iter(res.choices)).message.content)
            return normalize_script_payload(data, channel_name, topic)
        except Exception:
            pass
    return fallback_script(channel_name, topic)

def create_cinematic_bg(openai_key, image_prompt):
    if openai_key and image_prompt:
        try:
            client = OpenAI(api_key=openai_key)
            img_res = client.images.generate(model="dall-e-3", prompt=image_prompt, size="1024x1792", n=1)
            img_url = next(iter(img_res.data)).url
            raw_img = Image.open(BytesIO(requests.get(img_url, timeout=25).content)).convert("RGB")
            raw_img = raw_img.resize((1200, 2133), Image.Resampling.LANCZOS)
            overlay = Image.new("RGBA", (1200, 2133), (5, 8, 18, 105))
            return Image.alpha_composite(raw_img.convert("RGBA"), overlay).convert("RGB")
        except Exception:
            pass
    base = Image.new("RGB", (1200, 2133), (8, 12, 26))
    draw = ImageDraw.Draw(base)
    for y in range(2133):
        r = int(8 + (y / 2133) * 20)
        g = int(14 + (y / 2133) * 32)
        b = int(38 + (y / 2133) * 75)
        draw.line([(0, y), (1200, y)], fill=(r, g, b))
    draw.ellipse([(-180, 200), (760, 1140)], fill=(28, 78, 216))
    draw.ellipse([(440, 980), (1380, 1920)], fill=(109, 40, 217))
    return base.filter(ImageFilter.GaussianBlur(radius=85))

def render_pro_short(channel_name, persona, topic, openai_key="", script_override=None,
                     title_override=None):
    os.makedirs("output", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:18]
    mp4_path = f"output/studio_{ts}.mp4"
    if script_override is not None:
        sentences = split_manual_script(script_override)
        title = (str(title_override or "").strip() or str(topic or "NEXUS Shorts").strip())[:100]
        img_prompt = ""
        full_script = script_override.strip()
    else:
        title, sentences, img_prompt = generate_script(channel_name, persona, topic, openai_key)
        full_script = " ".join(sentences)
    master_bg = create_cinematic_bg(openai_key, img_prompt)
    font_sub = get_korean_font(62)
    font_badge = get_korean_font(34)
    font_head = get_korean_font(42)
    clips = []
    audio_clips = []
    temp_files = []
    final_vid = None
    completed = False
    try:
        total_s = len(sentences)
        for idx, sent in enumerate(sentences):
            seg_mp3 = f"output/seg_{ts}_{idx}.mp3"
            seg_png = f"output/seg_{ts}_{idx}.png"
            temp_files.extend([seg_mp3, seg_png])
            generate_announcer_audio(sent, channel_name, seg_mp3)
            ac = AudioFileClip(seg_mp3)
            audio_clips.append(ac)
            dur = max(ac.duration, 1.2)
            zoom = 1.0 + (idx * 0.018)
            crop_w, crop_h = int(1080 / zoom), int(1920 / zoom)
            left = (1200 - crop_w) // 2
            top = (2133 - crop_h) // 2
            frame = master_bg.crop((left, top, left + crop_w, top + crop_h)).resize((1080, 1920), Image.Resampling.LANCZOS)
            draw = ImageDraw.Draw(frame, "RGBA")
            draw.rounded_rectangle([(56, 120), (1024, 295)], radius=28, fill=(10, 15, 30, 210), outline=(56, 189, 248, 160), width=3)
            draw.rounded_rectangle([(84, 145), (380, 192)], radius=12, fill=(37, 99, 235, 230))
            draw.text((102, 152), f"* {channel_name[:16]}", fill=(255, 255, 255), font=font_badge)
            clean_title = title.replace("#Shorts", "").strip()
            draw.text((88, 212), clean_title[:24], fill=(248, 250, 252), font=font_head)
            wrapped = textwrap.fill(sent, width=16)
            lines = wrapped.split("\\n")
            block_h = len(lines) * 90 + 50
            box_top = 940 - (block_h // 2)
            draw.rounded_rectangle([(64, box_top), (1016, box_top + block_h)], radius=24, fill=(5, 8, 18, 165))
            for li, line_txt in enumerate(lines):
                y_pos = box_top + 28 + (li * 90)
                x1, y1, x2, y2 = draw.textbbox((0, 0), line_txt, font=font_sub)
                x_pos = max(80, (1080 - (x2 - x1)) // 2)
                t_color = (250, 204, 21) if idx == 0 else ((56, 189, 248) if idx == total_s - 1 else (255, 255, 255))
                draw.text((x_pos, y_pos), line_txt, font=font_sub, fill=t_color, stroke_width=6, stroke_fill=(0, 0, 0))
            prog_w = int(960 * ((idx + 1) / total_s))
            draw.rounded_rectangle([(60, 1680), (1020, 1698)], radius=9, fill=(30, 41, 59, 200))
            draw.rounded_rectangle([(60, 1680), (60 + prog_w, 1698)], radius=9, fill=(56, 189, 248, 255))
            frame.convert("RGB").save(seg_png, format="PNG")
            clip = ImageClip(seg_png).with_duration(dur).with_audio(ac)
            clips.append(clip)
        final_vid = concatenate_videoclips(clips, method="chain")
        final_vid.write_videofile(
            mp4_path, fps=24, codec="libx264", audio_codec="aac",
            ffmpeg_params=["-pix_fmt", "yuv420p"], logger=None,
        )
        completed = True
        return mp4_path, title, full_script
    finally:
        # Close readers before deleting their backing files, including on render failures.
        if final_vid is not None:
            try:
                final_vid.close()
            except Exception:
                pass
        for clip in clips:
            try:
                clip.close()
            except Exception:
                pass
        for audio in audio_clips:
            try:
                audio.close()
            except Exception:
                pass
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except OSError:
                pass
        if not completed:
            try:
                if os.path.exists(mp4_path):
                    os.remove(mp4_path)
            except OSError:
                pass
