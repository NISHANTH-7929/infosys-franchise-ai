"""12 extra NLLB-200 languages (35 total with the apps' 23) + better source-language detection (script ranges, then langdetect for Latin-script languages)."""
EXTRA_LANGS = {"Portuguese (Português)": "por_Latn", "Russian (Русский)": "rus_Cyrl", "Korean (한국어)": "kor_Hang", "Turkish (Türkçe)": "tur_Latn", "Indonesian (Bahasa Indonesia)": "ind_Latn",
               "Vietnamese (Tiếng Việt)": "vie_Latn", "Thai (ไทย)": "tha_Thai", "Italian (Italiano)": "ita_Latn", "Dutch (Nederlands)": "nld_Latn", "Swahili (Kiswahili)": "swh_Latn",
               "Greek (Ελληνικά)": "ell_Grek", "Hebrew (עברית)": "heb_Hebr", "Polish (Polski)": "pol_Latn", "Persian (فارسی)": "pes_Arab"}
_ISO = {"fr": "fra_Latn", "de": "deu_Latn", "es": "spa_Latn", "pt": "por_Latn", "it": "ita_Latn", "nl": "nld_Latn", "id": "ind_Latn", "tr": "tur_Latn", "vi": "vie_Latn", "pl": "pol_Latn", "sw": "swh_Latn", "en": "eng_Latn"}
def extra_detect(text):
    """Returns an NLLB code or None (caller keeps its own result)."""
    kana = any('\u3040' <= c <= '\u30ff' for c in text); han = any('\u4e00' <= c <= '\u9fff' for c in text)
    for ch in text:
        if '\u0400' <= ch <= '\u04ff': return "rus_Cyrl"
        if '\uac00' <= ch <= '\ud7af': return "kor_Hang"
        if '\u0e00' <= ch <= '\u0e7f': return "tha_Thai"
        if '\u0370' <= ch <= '\u03ff': return "ell_Grek"
        if '\u0590' <= ch <= '\u05ff': return "heb_Hebr"
        if '\u0d80' <= ch <= '\u0dff': return "sin_Sinh"
    if han and not kana: return "zho_Hans"
    if kana: return "jpn_Jpan"
    if not any(ord(c) > 127 for c in text) and len(text.split()) < 4: return None
    try:
        from langdetect import detect, DetectorFactory; DetectorFactory.seed = 0; return _ISO.get(detect(text))
    except Exception: return None