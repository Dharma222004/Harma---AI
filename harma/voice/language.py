"""
Harma Voice — Language Support

Central registry for the spoken languages Harma understands and speaks:
English (en-IN), Tamil (ta-IN) and Telugu (te-IN).

Responsibilities:
    - Map a language to its Google STT code and Microsoft Edge neural voices.
    - Detect spoken "switch language" commands ("Hey Harma, switch to Tamil",
      "தமிழில் பேசு", "తెలుగులో మాట్లాడు").
    - Strip the wake phrase ("hey harma") from transcripts in any script.
    - Classify yes / no / cancel / end-of-conversation replies in every language.
    - Provide short localized phrases the assistant speaks itself.

No audio, network or agent logic lives here — pure, unit-testable text helpers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class Language:
    code: str                      # short code: "en" | "ta" | "te"
    name: str                      # English name
    native_name: str               # name in its own script
    stt_code: str                  # Google STT BCP-47 code
    voice_female: str              # Edge neural voice (female)
    voice_male: str                # Edge neural voice (male)
    keywords: Tuple[str, ...]      # words that refer to this language
    phrases: Dict[str, str] = field(default_factory=dict, hash=False, compare=False)

    def voice(self, gender: str = "female") -> str:
        return self.voice_male if str(gender).lower().startswith("m") else self.voice_female

    def say(self, key: str) -> str:
        """Localized assistant phrase (falls back to English)."""
        return self.phrases.get(key) or ENGLISH.phrases.get(key, "")


_EN_PHRASES = {
    "ready": "Hey! I'm ready. Just say Hey Harma whenever you need me.",
    "listening": "Yes?",
    "not_caught": "Sorry, I didn't catch that.",
    "cancelled": "Okay, I've stopped that task.",
    "nothing_to_cancel": "There's nothing running right now.",
    "switched": "Okay, I'll speak in English from now on.",
    "busy": "I'm still working on your previous request. Say Hey Harma, stop, to cancel it.",
    "error": "Sorry, something went wrong. Please try again.",
    "confirm_retry": "Please say yes to confirm, or no to cancel.",
    "goodbye": "Okay. Call me anytime by saying Hey Harma.",
    "shutdown": "Turning off voice mode. Goodbye!",
    "offline": "I can't reach the speech service. Please check your internet connection.",
    "reset": "Okay, I've cleared our conversation.",
    "working": "On it.",
}

_TA_PHRASES = {
    "ready": "வணக்கம்! நான் தயார். தேவைப்படும்போது ஹே ஹர்மா என்று அழையுங்கள்.",
    "listening": "சொல்லுங்க?",
    "not_caught": "மன்னிக்கவும், சரியாக கேட்கவில்லை.",
    "cancelled": "சரி, அந்த வேலையை நிறுத்திவிட்டேன்.",
    "nothing_to_cancel": "இப்போது எந்த வேலையும் நடக்கவில்லை.",
    "switched": "சரி, இனி தமிழில் பேசுகிறேன்.",
    "busy": "முந்தைய வேலையை இன்னும் செய்து கொண்டிருக்கிறேன். நிறுத்த, ஹே ஹர்மா நிறுத்து என்று சொல்லுங்கள்.",
    "error": "மன்னிக்கவும், ஏதோ தவறு நடந்துவிட்டது. மீண்டும் முயற்சிக்கவும்.",
    "confirm_retry": "உறுதிப்படுத்த ஆமாம் என்றும், ரத்து செய்ய வேண்டாம் என்றும் சொல்லுங்கள்.",
    "goodbye": "சரி. தேவைப்பட்டால் ஹே ஹர்மா என்று அழையுங்கள்.",
    "shutdown": "குரல் முறையை நிறுத்துகிறேன். நன்றி!",
    "offline": "பேச்சு சேவையை அணுக முடியவில்லை. இணைய இணைப்பை சரிபார்க்கவும்.",
    "reset": "சரி, நம் உரையாடலை அழித்துவிட்டேன்.",
    "working": "சரி, செய்கிறேன்.",
}

_TE_PHRASES = {
    "ready": "నమస్తే! నేను సిద్ధంగా ఉన్నాను. అవసరమైనప్పుడు హే హర్మా అని పిలవండి.",
    "listening": "చెప్పండి?",
    "not_caught": "క్షమించండి, నాకు సరిగ్గా వినిపించలేదు.",
    "cancelled": "సరే, ఆ పనిని ఆపేశాను.",
    "nothing_to_cancel": "ప్రస్తుతం ఏ పనీ జరగడం లేదు.",
    "switched": "సరే, ఇకపై తెలుగులో మాట్లాడతాను.",
    "busy": "మునుపటి పనిని ఇంకా చేస్తున్నాను. ఆపడానికి, హే హర్మా ఆపు అని చెప్పండి.",
    "error": "క్షమించండి, ఏదో పొరపాటు జరిగింది. దయచేసి మళ్ళీ ప్రయత్నించండి.",
    "confirm_retry": "నిర్ధారించడానికి అవును అని, రద్దు చేయడానికి వద్దు అని చెప్పండి.",
    "goodbye": "సరే. అవసరమైతే హే హర్మా అని పిలవండి.",
    "shutdown": "వాయిస్ మోడ్ ఆపుతున్నాను. ధన్యవాదాలు!",
    "offline": "స్పీచ్ సేవను చేరుకోలేకపోతున్నాను. దయచేసి ఇంటర్నెట్ కనెక్షన్ చూడండి.",
    "reset": "సరే, మన సంభాషణను తొలగించాను.",
    "working": "సరే, చేస్తున్నాను.",
}

ENGLISH = Language(
    code="en", name="English", native_name="English", stt_code="en-IN",
    voice_female="en-IN-NeerjaNeural", voice_male="en-IN-PrabhatNeural",
    keywords=("english", "inglish", "ஆங்கிலம்", "இங்கிலீஷ்", "ఇంగ్లీష్", "ఆంగ్లం"),
    phrases=_EN_PHRASES,
)
TAMIL = Language(
    code="ta", name="Tamil", native_name="தமிழ்", stt_code="ta-IN",
    voice_female="ta-IN-PallaviNeural", voice_male="ta-IN-ValluvarNeural",
    keywords=("tamil", "thamil", "tamizh", "thamizh", "தமிழ்", "தமிழில்", "తమిళం"),
    phrases=_TA_PHRASES,
)
TELUGU = Language(
    code="te", name="Telugu", native_name="తెలుగు", stt_code="te-IN",
    voice_female="te-IN-ShrutiNeural", voice_male="te-IN-MohanNeural",
    keywords=("telugu", "telegu", "thelugu", "తెలుగు", "తెలుగులో", "தெலுங்கு"),
    phrases=_TE_PHRASES,
)

LANGUAGES: Dict[str, Language] = {lang.code: lang for lang in (ENGLISH, TAMIL, TELUGU)}


def resolve_language(value: object, default: Language = ENGLISH) -> Language:
    """Accepts Language object, or 'ta', 'ta-IN', 'tamil', 'Tamil', 'தமிழ்' … and returns a Language."""
    if isinstance(value, Language):
        return value
    if not value:
        return default
    v = str(value).strip().lower()
    if v in LANGUAGES:
        return LANGUAGES[v]
    for lang in LANGUAGES.values():
        if v == lang.stt_code.lower() or v.split("-")[0] == lang.code or v in lang.keywords:
            return lang
    return default


# ─────────────────────────────────────────────────────────────────────────────
# Text normalisation
# ─────────────────────────────────────────────────────────────────────────────

_APOSTROPHE_RE = re.compile(r"['’‘`]")
_PUNCT_RE = re.compile(r"[\s,.!?;:\"“”()\-–—।]+")


def normalize(text: str) -> str:
    """Lower-case, strip intra-word apostrophes, collapse punctuation/whitespace."""
    if not text:
        return ""
    t = _APOSTROPHE_RE.sub("", str(text).lower())
    return _PUNCT_RE.sub(" ", t).strip()


def _has_phrase(norm_text: str, phrases) -> bool:
    padded = f" {norm_text} "
    return any(f" {normalize(p)} " in padded for p in phrases)


# ─────────────────────────────────────────────────────────────────────────────
# Wake phrase stripping
# ─────────────────────────────────────────────────────────────────────────────

# How Google STT commonly writes "Hey Harma" (English + Tamil + Telugu scripts).
_WAKE_GREETING = r"(?:hey|hay|hei|he|hi|hii|a|ok|okay|ஹே|ஹாய்|హే|హాయ్)"
_WAKE_NAME = (
    r"(?:harma|haarma|harmaa|hharma|karma|kharma|carma|hama|hamma|harmer|harmar|parma|"
    r"arma|herma|hurma|horma|sharma|varma|burma|"
    r"ஹர்மா|ஹார்மா|கர்மா|ஹர்மாவே|"
    r"హర్మా|హర్మ|హార్మా|కర్మ)"
)
_WAKE_RE = re.compile(
    rf"^\s*(?:{_WAKE_GREETING}[\s,.!?:\-]*)?{_WAKE_NAME}(?=$|[\s,.!?:\-])[\s,.!?:\-]*",
    re.IGNORECASE,
)
_GREETING_ONLY_RE = re.compile(rf"^\s*{_WAKE_GREETING}[\s,.!?:\-]*$", re.IGNORECASE)


def strip_wake_phrase(text: str) -> str:
    """
    Remove a leading "hey harma" (and its common mis-transcriptions) from text.

    "Hey Harma, open notepad"  → "open notepad"
    "hey karma what's the time" → "what's the time"
    "ஹே ஹர்மா நேரம் என்ன"       → "நேரம் என்ன"
    "Hey Harma"                 → ""
    """
    if not text:
        return ""
    stripped = _WAKE_RE.sub("", text, count=1).strip()
    if _GREETING_ONLY_RE.match(stripped):
        return ""
    return stripped


# ─────────────────────────────────────────────────────────────────────────────
# Intent helpers (language switch, yes/no, cancel, end conversation, shutdown)
# ─────────────────────────────────────────────────────────────────────────────

_SWITCH_VERBS = (
    "switch", "change", "speak", "talk", "reply", "respond", "answer", "use", "set",
    "language", "mode", "in", "pesu", "pesungal", "pesunga", "matladu", "matladandi",
    "பேசு", "பேசுங்கள்", "பேசுங்க", "மாற்று", "மாத்து", "மொழி",
    "మాట్లాడు", "మాట్లాడండి", "మార్చు", "భాష",
)


def detect_language_switch(text: str) -> Optional[Language]:
    """
    Return the target Language if the utterance is a request to change the
    conversation language, else None.

    Matches short commands only, so "search tamil movies near me" or
    "translate hello to telugu" are NOT treated as language switches.
    """
    norm = normalize(strip_wake_phrase(text))
    if not norm:
        return None
    words = norm.split()
    target = None
    for lang in LANGUAGES.values():
        if any(w in lang.keywords or w.rstrip("ல").rstrip("లో") in lang.keywords for w in words):
            target = lang
            break
        if any(k in norm for k in lang.keywords if not k.isascii()):
            target = lang
            break
    if target is None:
        return None
    if any(w in ("translate", "translation", "meaning", "search", "find", "movie", "movies", "song", "songs", "news") for w in words):
        return None
    if len(words) <= 2:
        return target
    if len(words) <= 6 and any(w in _SWITCH_VERBS for w in words):
        return target
    return None


_YES = (
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "confirm", "confirmed", "go ahead",
    "do it", "proceed", "continue", "correct", "right", "please do",
    "ஆமா", "ஆமாம்", "சரி", "ஓகே", "செய்", "செய்யுங்கள்", "aama", "aamaa", "aamam", "sari", "seri",
    "అవును", "సరే", "ఓకే", "చేయి", "చేయండి", "avunu", "sare",
)
_NO = (
    "no", "nope", "nah", "cancel", "don't", "dont", "do not", "stop", "abort", "never mind",
    "nevermind", "not now", "wait",
    "வேண்டாம்", "இல்லை", "வேணாம்", "venda", "vendam", "venam", "illai", "illa",
    "వద్దు", "కాదు", "లేదు", "ఆపు", "vaddu", "kaadu", "ledu",
)


def classify_yes_no(text: str) -> Optional[str]:
    """Return 'yes', 'no' or None (ambiguous). Negative words win."""
    norm = normalize(strip_wake_phrase(text))
    if not norm:
        return None
    if _has_phrase(norm, _NO):
        return "no"
    if _has_phrase(norm, _YES):
        return "yes"
    return None


_CANCEL = (
    "stop", "stop it", "cancel", "cancel it", "abort", "halt", "never mind", "nevermind",
    "stop the task", "cancel the task", "stop that", "cancel that",
    "நிறுத்து", "நிறுத்துங்கள்", "நிறுத்துங்க", "வேண்டாம்", "niruthu", "nirutthu",
    "ఆపు", "ఆపండి", "ఆపేయి", "వద్దు", "aapu", "aapandi",
)


def is_cancel_command(text: str) -> bool:
    norm = normalize(strip_wake_phrase(text))
    return bool(norm) and len(norm.split()) <= 4 and _has_phrase(norm, _CANCEL)


_END_CONVERSATION = (
    "thank you", "thanks", "thank you harma", "that's all", "thats all", "that is all",
    "goodbye", "bye", "bye bye", "nothing", "no thanks", "no thank you", "nothing else",
    "நன்றி", "போதும்", "அவ்வளவுதான்", "சரி நன்றி", "nandri", "bodhum", "podhum",
    "ధన్యవాదాలు", "చాలు", "అంతే", "థాంక్స్", "dhanyavadalu", "chaalu",
)


def is_end_conversation(text: str) -> bool:
    norm = normalize(strip_wake_phrase(text))
    return bool(norm) and len(norm.split()) <= 4 and _has_phrase(norm, _END_CONVERSATION)


_SHUTDOWN = (
    "exit voice mode", "quit voice mode", "turn off voice", "turn off voice mode",
    "shutdown voice", "shut down voice", "stop listening", "quit voice assistant",
    "exit voice assistant", "goodbye harma", "bye harma", "shutdown", "shut down",
)


def is_shutdown_command(text: str) -> bool:
    raw = normalize(text)
    norm = normalize(strip_wake_phrase(text))
    return any(p == raw or p == norm for p in _SHUTDOWN)


_RESET = ("reset", "clear memory", "clear conversation", "start over", "forget everything", "new conversation")


def is_reset_command(text: str) -> bool:
    norm = normalize(strip_wake_phrase(text))
    return norm in _RESET


def reply_instruction(lang: Language) -> str:
    """Instruction appended to agent input so it answers in the spoken language."""
    if lang.code == "en":
        return ""
    return (
        f"\n\n[Voice mode: the user spoke in {lang.name}. Perform the task normally, then reply "
        f"in {lang.name} using {lang.name} script ({lang.native_name}). Keep the reply short and "
        f"conversational because it will be spoken aloud.]"
    )
