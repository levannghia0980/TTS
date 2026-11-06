from typing import List, Dict, Optional

# Danh sách các giọng đọc Tiếng Việt chuẩn tuyển chọn (Chỉ hiện các giọng Việt chất lượng trên giao diện)
ALL_VOICES: List[Dict[str, str]] = [
    # --- Top Giọng Nữ Tiếng Việt Hay Nhất (CapCut & Edge) ---
    {"id": "BV074_streaming", "name": "Nữ: Cô Gái Hoạt Ngôn (Review Trend, Sôi nổi - Khuyên dùng)", "gender": "female"},
    {"id": "vi-VN-HoaiMyNeural", "name": "Nữ: Hoài My (Truyền cảm, Ngọt ngào, Đọc truyện)", "gender": "female"},
    {"id": "BV562_streaming", "name": "Nữ: Mai (Trầm ấm, Thanh lịch, Kể chuyện dài)", "gender": "female"},
    {"id": "BV421_vivn_streaming", "name": "Nữ: Nhỏ Ngọt Ngào (Êm ái, Dịu dàng)", "gender": "female"},
    {"id": "vi_female_huong", "name": "Nữ: Hương (Chuẩn Phổ thông miền Bắc)", "gender": "female"},
    {"id": "local_ngoc_huyen_new", "name": "🇻🇳 [Offline Local] Nữ: Ngọc Huyền New (AIRead)", "gender": "female"},

    # --- Top Giọng Nam Tiếng Việt Hay Nhất (CapCut) ---
    {"id": "BV075_streaming", "name": "Nam: Hào Sảng (Trầm ấm, Thuyết minh phim chuẩn)", "gender": "male"},
    {"id": "BV560_streaming", "name": "Nam: Alex Hùng Tráng (Khí phách, Sử thi)", "gender": "male"},
]

# Ánh xạ ngôn ngữ → giọng nam đặc trưng quốc gia từ CapCut / Edge TTS
# Tuyển chọn các giọng nam chuyên nghiệp nhất: rõ chữ, tròn âm, chuẩn mực ngữ điệu.
LANG_TO_MALE_VOICE: Dict[str, str] = {
    # Tiếng Anh: CapCut Male Profess (Chuyên nghiệp, phát âm rõ từng chữ, nghiêm túc chuẩn mực)
    "en": "en_us_007",
    "en-us": "en_us_007",
    "en-gb": "en_us_007",

    # Tiếng Trung: CapCut Youyou Junzi (優優君子 - Giọng nam đĩnh đạc, phát âm chuẩn Bắc Kinh, rất rõ chữ)
    "zh": "multi_zh_male_youyoujunzi_moon_bigtts_cc",
    "zh-cn": "multi_zh_male_youyoujunzi_moon_bigtts_cc",
    "zh-tw": "multi_zh_male_youyoujunzi_moon_bigtts_cc",
    "zh-hk": "multi_zh_male_youyoujunzi_moon_bigtts_cc",

    # Tiếng Việt: CapCut Nam Hào Sảng (Trầm ấm, rõ từng chữ, phong cách thuyết minh chuẩn)
    "vi": "BV075_streaming",
    "vi-vn": "BV075_streaming",

    # Tiếng Nhật: CapCut 穏やかな声優 (ICL_ja_male_bobao2 - Điềm đạm, rõ ràng)
    "ja": "ICL_ja_male_bobao2",
    "ja-jp": "ICL_ja_male_bobao2",

    # Tiếng Tây Ban Nha: CapCut EdgarRu (ICL_es_male_tt_EdgarRu - Nam chuẩn Tây Ban Nha)
    "es": "ICL_es_male_tt_EdgarRu",
    "es-es": "ICL_es_male_tt_EdgarRu",

    # Tiếng Bồ Đào Nha: CapCut LuizS (ICL_br_male_212M_LuizS - Nam chuẩn Bồ Đào Nha)
    "pt": "ICL_br_male_212M_LuizS",
    "pt-br": "ICL_br_male_212M_LuizS",

    # Tiếng Indonesia: CapCut Deep God (ICL_id_male_deep_god_dsp)
    "id": "ICL_id_male_deep_god_dsp",
    "id-id": "ICL_id_male_deep_god_dsp",

    # Các quốc gia lớn khác dùng Edge-TTS Neural Male chuẩn phát thanh viên
    "fr": "fr-FR-HenriNeural",                     # Tiếng Pháp
    "de": "de-DE-ConradNeural",                    # Tiếng Đức
    "ko": "ko-KR-InJoonNeural",                    # Tiếng Hàn
    "it": "it-IT-GiuseppeMultilingualNeural",      # Tiếng Ý
    "ru": "ru-RU-DmitryNeural",                    # Tiếng Nga
    "th": "th-TH-NiwatNeural",                     # Tiếng Thái
}

_FALLBACK_CHAIN = ["en", "zh", "vi"]


def get_male_voice_for_lang(lang_code: str) -> str:
    """
    Trả về voice_id giọng nam đặc trưng cho ngôn ngữ phát hiện từ trang web.
    Tuyển chọn giọng CapCut chuyên nghiệp, rõ chữ, chuẩn mực nhất.
    Fallback chain: exact match → base language → en → zh → vi
    """
    if not lang_code:
        return LANG_TO_MALE_VOICE["en"]

    lower = lang_code.lower().strip()

    # Exact match (ví dụ: 'zh-CN', 'en-US')
    if lower in LANG_TO_MALE_VOICE:
        return LANG_TO_MALE_VOICE[lower]

    # Base language (ví dụ: 'zh-CN' → 'zh', 'en-US' → 'en')
    base = lower.split("-")[0].split("_")[0]
    if base in LANG_TO_MALE_VOICE:
        return LANG_TO_MALE_VOICE[base]

    # Fallback chain: en -> zh -> vi
    for fb in _FALLBACK_CHAIN:
        if fb in LANG_TO_MALE_VOICE:
            return LANG_TO_MALE_VOICE[fb]

    return "en_us_007"
