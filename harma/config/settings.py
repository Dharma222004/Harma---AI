"""
Harma Configuration

Centralizes all configuration. Values are read from environment variables first,
then from config.yaml if present, then fall back to defaults.

The design intentionally separates secrets (env vars / .env file) from
non-sensitive settings (config.yaml) so the user never has to edit Python code.
"""

from __future__ import annotations

import os
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parent.parent.parent  # repo root
CONFIG_FILE = ROOT_DIR / "config.yaml"
ENV_FILE = ROOT_DIR / ".env"


def _load_env_file() -> None:
    """Manually parse a .env file and inject into os.environ."""
    if not ENV_FILE.exists():
        return
    with open(ENV_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _load_yaml_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data or {}
    return {}


@dataclass
class LLMConfig:
    """Configuration for the active LLM provider."""

    provider: str = "gemini"          # gemini | groq | openai | claude | ollama
    api_key: str = ""                 # primary key (used by adapter)
    api_keys: list = field(default_factory=list)  # all keys for rotation
    model: str = "gemini-2.5-flash"
    base_url: Optional[str] = None    # for OpenAI-compatible / custom endpoints
    temperature: float = 0.2
    max_tokens: int = 8192
    timeout: int = 60                 # seconds
    stream: bool = True
    # Groq-specific
    groq_keys: list = field(default_factory=list)
    groq_model: str = "openai/gpt-oss-20b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    # NVIDIA-specific
    nvidia_api_key: str = ""
    nvidia_keys: list = field(default_factory=list)
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = ""
    nvidia_timeout: int = 120
    nvidia_temperature: float = 0.2
    fallback_enabled: bool = False


@dataclass
class AgentConfig:
    """Core agent runtime configuration."""

    name: str = "Harma"
    max_iterations: int = 100         # max tool-call iterations per task
    max_retries: int = 3              # retries on transient tool errors
    verbose_logging: bool = True
    task_timeout_seconds: float = 600.0  # task execution deadline in seconds (default 10 min)
    runtime: str = "v2"               # "v2" = existing ExecutionEngine (default) | "v3" = Harma Runtime V3 (opt-in)


@dataclass
class PermissionsConfig:
    """Default permission thresholds."""

    auto_confirm_safe: bool = True           # SAFE actions run without asking
    auto_confirm_sensitive: bool = False     # SENSITIVE actions ask the user
    auto_confirm_high_risk: bool = False     # HIGH_RISK always ask, no override


@dataclass
class MemoryRetrievalConfig:
    """Phase 5 retrieval settings."""
    enabled: bool = True
    top_k: int = 8
    max_context_tokens: int = 1500
    min_score: float = 0.05


@dataclass
class MemoryConfig:
    """Memory system configuration."""

    short_term_max_messages: int = 40
    long_term_db_path: str = str(ROOT_DIR / "data" / "harma_memory.db")
    enable_long_term: bool = True

    # Phase 5 additions
    retrieval_enabled: bool = True
    retrieval_top_k: int = 8
    retrieval_max_context_tokens: int = 1500
    auto_extract: bool = True       # auto-extract memories from explicit user statements
    secret_detection: bool = True   # block credential storage
    retention_enabled: bool = True

    # Nested retrieval config (convenience accessor)
    @property
    def retrieval(self) -> "MemoryRetrievalConfig":
        return MemoryRetrievalConfig(
            enabled=self.retrieval_enabled,
            top_k=self.retrieval_top_k,
            max_context_tokens=self.retrieval_max_context_tokens,
        )


@dataclass
class ComputerConfig:
    """Phase 2 computer control configuration."""

    enabled: bool = True
    screenshot_enabled: bool = True
    mouse_enabled: bool = True
    mouse_failsafe: bool = True
    keyboard_enabled: bool = True
    keyboard_type_interval: float = 0.03
    window_control_enabled: bool = True
    window_focus_timeout: float = 3.0
    ui_detection_enabled: bool = True
    ui_detection_strategy: str = "accessibility"
    ui_detection_confidence: float = 0.8
    safety_action_interval: float = 0.05
    safety_post_action_delay: float = 0.5


@dataclass
class BrowserConfig:
    """Phase 3 browser automation configuration."""

    enabled: bool = True
    engine: str = "playwright"          # automation engine
    browser: str = "chromium"           # chromium | firefox | webkit
    headless: bool = False              # show browser window
    persistent_profile: bool = True     # keep login sessions across runs
    profile_dir: str = ""               # path to persistent profile dir (empty = data/browser_profile)
    downloads_enabled: bool = True
    downloads_dir: str = ""             # empty = default (~/Downloads/harma)
    uploads_enabled: bool = True
    max_pages_per_task: int = 20        # navigation limit per task
    search_engine: str = "https://www.google.com"
    require_confirmation_sensitive: bool = True  # confirm before form submit etc.
    slow_mo_ms: int = 50                # ms delay between Playwright actions


@dataclass
class VoiceConfig:
    """Phase 4 voice system configuration."""

    enabled: bool = True

    # Wake word
    wake_word_enabled: bool = False      # False = push-to-talk mode
    wake_word_phrase: str = "hey harma"

    # Microphone
    microphone_device: str = "default"
    microphone_sample_rate: int = 16_000
    microphone_channels: int = 1

    # VAD
    vad_enabled: bool = True
    vad_silence_timeout_ms: int = 1200
    vad_min_speech_ms: int = 250

    # STT
    stt_provider: str = "google"         # google | whisper | offline
    stt_language: str = "en-IN"
    stt_timeout: float = 15.0

    # TTS
    tts_provider: str = "pyttsx3"        # pyttsx3 | silent
    tts_rate: int = 175                  # words per minute
    tts_volume: float = 0.95             # 0.0–1.0
    tts_voice_id: str = ""               # empty = system default

    # Conversation mode
    conversation_mode_enabled: bool = False
    conversation_inactivity_timeout: float = 30.0
    conversation_max_duration: float = 600.0

    # Listening
    listen_timeout: float = 15.0         # max seconds to wait for speech

    # Privacy
    save_recordings: bool = False        # never save audio to disk by default
    recordings_dir: str = ""             # empty = logs/recordings/


@dataclass
class AndroidConfig:
    """Phase 6 Android mobile control configuration."""

    enabled: bool = True
    transport: str = "adb"               # adb | mock
    adb_path: str = "adb"
    device_id: str = ""                  # empty = default / auto-select
    action_timeout_seconds: float = 15.0
    retry_count: int = 1
    include_screenshots: bool = True
    save_screenshots: bool = False
    screenshots_dir: str = ""
    detect_secrets: bool = True


@dataclass
class TasksConfig:
    """Phase 7 proactive tasks & autonomous execution configuration."""

    enabled: bool = True
    timezone: str = "UTC"
    db_path: str = str(ROOT_DIR / "data" / "harma_tasks.db")
    max_concurrent_tasks: int = 3
    default_max_runtime_seconds: float = 300.0
    default_max_steps: int = 50
    min_condition_poll_interval: float = 60.0
    dry_run: bool = False
    quiet_hours_enabled: bool = False
    quiet_hours_start: str = "22:00"
    quiet_hours_end: str = "07:00"


@dataclass
class IntegrationsConfig:
    """Phase 8 MCP & external service integrations configuration."""

    enabled: bool = True
    mcp_enabled: bool = True
    default_timeout_seconds: float = 30.0
    auto_connect_on_startup: bool = True
    circuit_breaker_failure_threshold: int = 3
    circuit_breaker_cooldown_seconds: float = 30.0
    dry_run: bool = False
    servers: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class IntelligenceConfig:
    """Phase 9 unified intelligence, multimodal perception & planning configuration."""

    planning_enabled: bool = True
    planning_max_steps: int = 20
    planning_max_retries: int = 3
    context_max_tokens: int = 8000
    context_memory_limit: int = 5
    context_observation_limit: int = 10
    multimodal_enabled: bool = True
    vision_provider: str = "mock"
    model_router_enabled: bool = True
    verification_required_for_side_effects: bool = True
    dry_run: bool = False


@dataclass
class UIConfig:
    """Phase 10 Harma Control Center UI & API configuration."""

    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    session_timeout_minutes: int = 60
    require_auth: bool = False
    dev_mode: bool = False


@dataclass
class PerformanceConfig:
    """Execution Performance V2 settings."""

    mode: str = "balanced"                    # balanced | fast | debug
    max_llm_calls: int = 100                  # max LLM reasoning cycles per request
    context_budget: int = 16000               # max context tokens budget
    tool_schema_cache: bool = True            # cache OpenAI tool schemas
    tool_routing_cache: bool = True           # cache hierarchical tool routing index
    session_reuse: bool = True                # reuse LLM/Playwright/ADB/DB sessions
    streaming: bool = True                    # stream responses when supported
    fast_path: bool = True                    # safe deterministic fast-path for trivial/single tools
    conditional_observation: bool = True      # observe only relevant state
    reasoning_budget_enabled: bool = True     # enforce reasoning budget per classification


@dataclass
class HarmaConfig:
    """Top-level configuration object. Pass this around rather than globals."""

    llm: LLMConfig = field(default_factory=LLMConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    permissions: PermissionsConfig = field(default_factory=PermissionsConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    computer: ComputerConfig = field(default_factory=ComputerConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    android: AndroidConfig = field(default_factory=AndroidConfig)
    tasks: TasksConfig = field(default_factory=TasksConfig)
    integrations: IntegrationsConfig = field(default_factory=IntegrationsConfig)
    intelligence: IntelligenceConfig = field(default_factory=IntelligenceConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    performance: PerformanceConfig = field(default_factory=PerformanceConfig)


def load_config() -> HarmaConfig:
    """
    Build and return the active HarmaConfig.

    Priority (highest → lowest):
      1. Environment variables
      2. .env file (root of repo)
      3. config.yaml (root of repo)
      4. Hardcoded defaults in dataclasses
    """
    _load_env_file()
    yaml_cfg = _load_yaml_config()

    llm_yaml = yaml_cfg.get("llm", {})
    agent_yaml = yaml_cfg.get("agent", {})
    perms_yaml = yaml_cfg.get("permissions", {})
    mem_yaml = yaml_cfg.get("memory", {})

    # ── Collect all Gemini keys for rotation ─────────────────────────────────
    _primary_key = os.environ.get("HARMA_API_KEY", llm_yaml.get("api_key", ""))
    _gemini_keys_raw = [
        _primary_key,
        os.environ.get("GEMINI_API_KEY_1", ""),
        os.environ.get("GEMINI_API_KEY_2", ""),
        os.environ.get("GEMINI_API_KEY_3", ""),
        os.environ.get("GEMINI_API_KEY_4", ""),
    ]
    _seen: set = set()
    _gemini_keys = [k for k in _gemini_keys_raw if k and k not in _seen and not _seen.add(k)]

    # ── Collect all Groq keys for rotation ────────────────────────────────────
    _groq_keys = [
        k for k in [
            os.environ.get("GROQ_API_KEY_1", ""),
            os.environ.get("GROQ_API_KEY_2", ""),
            os.environ.get("GROQ_API_KEY_3", ""),
            os.environ.get("GROQ_API_KEY_4", ""),
        ]
        if k
    ]

    # ── Collect NVIDIA config & keys for rotation ─────────────────────────────
    _primary_nvidia_key = os.environ.get("NVIDIA_API_KEY", llm_yaml.get("nvidia_api_key", ""))
    _nvidia_keys_raw = [
        _primary_nvidia_key,
        os.environ.get("NVIDIA_API_KEY_1", ""),
        os.environ.get("NVIDIA_API_KEY_2", ""),
        os.environ.get("NVIDIA_API_KEY_3", ""),
        os.environ.get("NVIDIA_API_KEY_4", ""),
    ]
    _extra_nvidia = os.environ.get("NVIDIA_API_KEYS", "")
    if _extra_nvidia:
        _nvidia_keys_raw.extend(k.strip() for k in _extra_nvidia.split(","))

    _nv_seen: set = set()
    _nvidia_keys = [k for k in _nvidia_keys_raw if k and k not in _nv_seen and not _nv_seen.add(k)]
    _nvidia_key = _nvidia_keys[0] if _nvidia_keys else _primary_nvidia_key
    _nvidia_model = os.environ.get("NVIDIA_MODEL", llm_yaml.get("nvidia_model", ""))
    _nvidia_base_url = os.environ.get(
        "NVIDIA_BASE_URL",
        llm_yaml.get("nvidia_base_url", "https://integrate.api.nvidia.com/v1")
    )
    _nvidia_timeout = int(os.environ.get("NVIDIA_TIMEOUT", llm_yaml.get("nvidia_timeout", 120)))
    _nvidia_temp = float(os.environ.get("NVIDIA_TEMPERATURE", llm_yaml.get("nvidia_temperature", 0.2)))
    _fallback_enabled = str(
        os.environ.get("HARMA_LLM_FALLBACK_ENABLED", llm_yaml.get("fallback_enabled", False))
    ).lower() == "true"

    _provider_env = os.environ.get("HARMA_LLM_PROVIDER")
    if _provider_env:
        _active_provider = _provider_env
    elif _nvidia_key or _nvidia_model:
        _active_provider = "nvidia"
    else:
        _active_provider = llm_yaml.get("provider", "gemini")

    if _active_provider == "nvidia":
        _active_key = _nvidia_key
        _active_keys = _nvidia_keys
        _active_model = _nvidia_model
        _active_base_url = _nvidia_base_url
        _active_timeout = _nvidia_timeout
        _active_temp = _nvidia_temp
    else:
        _active_key = _gemini_keys[0] if _gemini_keys else ""
        _active_keys = _gemini_keys
        _active_model = os.environ.get("HARMA_MODEL", llm_yaml.get("model", "gemini-2.5-flash"))
        _active_base_url = os.environ.get("HARMA_BASE_URL", llm_yaml.get("base_url")) or None
        _active_timeout = int(os.environ.get("HARMA_TIMEOUT", llm_yaml.get("timeout", 60)))
        _active_temp = float(os.environ.get("HARMA_TEMPERATURE", llm_yaml.get("temperature", 0.2)))

    llm = LLMConfig(
        provider=_active_provider,
        api_key=_active_key,
        api_keys=_active_keys,
        model=_active_model,
        base_url=_active_base_url,
        temperature=_active_temp,
        max_tokens=int(os.environ.get("HARMA_MAX_TOKENS", llm_yaml.get("max_tokens", 8192))),
        timeout=_active_timeout,
        stream=str(os.environ.get("HARMA_STREAM", llm_yaml.get("stream", True))).lower() != "false",
        groq_keys=_groq_keys,
        groq_model=os.environ.get("GROQ_MODEL", llm_yaml.get("groq_model", "openai/gpt-oss-20b")),
        groq_base_url=os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
        nvidia_api_key=_nvidia_key,
        nvidia_keys=_nvidia_keys,
        nvidia_base_url=_nvidia_base_url,
        nvidia_model=_nvidia_model,
        nvidia_timeout=_nvidia_timeout,
        nvidia_temperature=_nvidia_temp,
        fallback_enabled=_fallback_enabled,
    )

    agent = AgentConfig(
        name=os.environ.get("HARMA_NAME", agent_yaml.get("name", "Harma")),
        max_iterations=int(os.environ.get("HARMA_MAX_ITER", agent_yaml.get("max_iterations", 50))),
        max_retries=int(os.environ.get("HARMA_MAX_RETRIES", agent_yaml.get("max_retries", 3))),
        verbose_logging=str(os.environ.get("HARMA_VERBOSE", agent_yaml.get("verbose_logging", True))).lower() != "false",
        task_timeout_seconds=float(os.environ.get("HARMA_TASK_TIMEOUT", agent_yaml.get("task_timeout_seconds", 600.0))),
        runtime=str(os.environ.get("HARMA_RUNTIME", agent_yaml.get("runtime", "v2"))).strip().lower(),
    )

    perms_auto_sensitive = os.environ.get(
        "HARMA_AUTO_CONFIRM_SENSITIVE",
        str(perms_yaml.get("auto_confirm_sensitive", False)),
    )
    permissions = PermissionsConfig(
        auto_confirm_safe=str(os.environ.get("HARMA_AUTO_CONFIRM_SAFE", perms_yaml.get("auto_confirm_safe", True))).lower() != "false",
        auto_confirm_sensitive=str(perms_auto_sensitive).lower() in ("true", "1", "yes"),
        auto_confirm_high_risk=False,  # never auto-confirm high risk
    )

    mem_retrieval = mem_yaml.get("retrieval", {})
    mem_extraction = mem_yaml.get("extraction", {})
    mem_privacy = mem_yaml.get("privacy", {})
    mem_retention = mem_yaml.get("retention", {})

    memory = MemoryConfig(
        short_term_max_messages=int(mem_yaml.get("short_term_max_messages", 40)),
        long_term_db_path=mem_yaml.get("long_term_db_path", str(ROOT_DIR / "data" / "harma_memory.db")),
        enable_long_term=str(mem_yaml.get("enable_long_term", True)).lower() != "false",
        retrieval_enabled=str(mem_retrieval.get("enabled", mem_yaml.get("retrieval_enabled", True))).lower() != "false",
        retrieval_top_k=int(mem_retrieval.get("top_k", mem_yaml.get("retrieval_top_k", 8))),
        retrieval_max_context_tokens=int(mem_retrieval.get("max_context_tokens", mem_yaml.get("retrieval_max_context_tokens", 1500))),
        auto_extract=str(mem_extraction.get("auto_save", mem_yaml.get("auto_extract", True))).lower() != "false",
        secret_detection=str(mem_privacy.get("secret_detection", mem_yaml.get("secret_detection", True))).lower() != "false",
        retention_enabled=str(mem_retention.get("enabled", mem_yaml.get("retention_enabled", True))).lower() != "false",
    )

    comp_yaml = yaml_cfg.get("computer", {})
    comp_mouse = comp_yaml.get("mouse", {})
    comp_keyboard = comp_yaml.get("keyboard", {})
    comp_window = comp_yaml.get("window_control", {})
    comp_uid = comp_yaml.get("ui_detection", {})
    comp_safety = comp_yaml.get("safety", {})
    comp_shot = comp_yaml.get("screenshot", {})

    computer = ComputerConfig(
        enabled=str(comp_yaml.get("enabled", True)).lower() != "false",
        screenshot_enabled=str(comp_shot.get("enabled", True)).lower() != "false",
        mouse_enabled=str(comp_mouse.get("enabled", True)).lower() != "false",
        mouse_failsafe=str(comp_mouse.get("failsafe", True)).lower() != "false",
        keyboard_enabled=str(comp_keyboard.get("enabled", True)).lower() != "false",
        keyboard_type_interval=float(comp_keyboard.get("type_interval", 0.03)),
        window_control_enabled=str(comp_window.get("enabled", True)).lower() != "false",
        window_focus_timeout=float(comp_window.get("focus_timeout", 3.0)),
        ui_detection_enabled=str(comp_uid.get("enabled", True)).lower() != "false",
        ui_detection_strategy=comp_uid.get("strategy", "accessibility"),
        ui_detection_confidence=float(comp_uid.get("confidence", 0.8)),
        safety_action_interval=float(comp_safety.get("action_interval", 0.05)),
        safety_post_action_delay=float(comp_safety.get("post_action_delay", 0.5)),
    )

    browser_yaml = yaml_cfg.get("browser", {})
    browser_nav = browser_yaml.get("navigation", {})
    browser_dl = browser_yaml.get("downloads", {})
    browser_ul = browser_yaml.get("uploads", {})
    browser_safety = browser_yaml.get("safety", {})

    browser = BrowserConfig(
        enabled=str(browser_yaml.get("enabled", True)).lower() != "false",
        engine=browser_yaml.get("engine", "playwright"),
        browser=browser_yaml.get("browser", "chromium"),
        headless=str(browser_yaml.get("headless", False)).lower() == "true",
        persistent_profile=str(browser_yaml.get("persistent_profile", True)).lower() != "false",
        profile_dir=browser_yaml.get("profile_dir", ""),
        downloads_enabled=str(browser_dl.get("enabled", True)).lower() != "false",
        downloads_dir=browser_dl.get("dir", ""),
        uploads_enabled=str(browser_ul.get("enabled", True)).lower() != "false",
        max_pages_per_task=int(browser_nav.get("max_pages_per_task", 20)),
        search_engine=browser_yaml.get("search_engine", "https://www.google.com"),
        require_confirmation_sensitive=str(
            browser_safety.get("require_confirmation_for_sensitive_actions", True)
        ).lower() != "false",
        slow_mo_ms=int(browser_yaml.get("slow_mo_ms", 50)),
    )

    return HarmaConfig(
        llm=llm, agent=agent, permissions=permissions,
        memory=memory, computer=computer, browser=browser,
        voice=_load_voice_config(yaml_cfg),
        android=_load_android_config(yaml_cfg),
        tasks=_load_tasks_config(yaml_cfg),
        integrations=_load_integrations_config(yaml_cfg),
        intelligence=_load_intelligence_config(yaml_cfg),
        ui=_load_ui_config(yaml_cfg),
        performance=_load_performance_config(yaml_cfg),
    )


def _load_performance_config(yaml_cfg: dict) -> "PerformanceConfig":
    """Load PerformanceConfig with env var precedence for Phase 10.5 / Performance V2."""
    p = yaml_cfg.get("performance", {})
    mode = os.environ.get("HARMA_PERFORMANCE_MODE", p.get("mode", "balanced")).lower()

    default_max_llm = 8 if mode == "fast" else 100
    max_llm = int(os.environ.get("HARMA_MAX_LLM_CALLS", p.get("max_llm_calls", default_max_llm)))

    return PerformanceConfig(
        mode=mode,
        max_llm_calls=max_llm,
        context_budget=int(os.environ.get("HARMA_CONTEXT_BUDGET", p.get("context_budget", 16000))),
        tool_schema_cache=str(os.environ.get("HARMA_TOOL_SCHEMA_CACHE", p.get("tool_schema_cache", True))).lower() != "false",
        tool_routing_cache=str(os.environ.get("HARMA_TOOL_ROUTING_CACHE", p.get("tool_routing_cache", True))).lower() != "false",
        session_reuse=str(os.environ.get("HARMA_SESSION_REUSE", p.get("session_reuse", True))).lower() != "false",
        streaming=str(os.environ.get("HARMA_STREAMING", p.get("streaming", True))).lower() != "false",
        fast_path=str(os.environ.get("HARMA_FAST_PATH", p.get("fast_path", True))).lower() != "false",
        conditional_observation=str(os.environ.get("HARMA_CONDITIONAL_OBSERVATION", p.get("conditional_observation", True))).lower() != "false",
        reasoning_budget_enabled=str(os.environ.get("HARMA_REASONING_BUDGET", p.get("reasoning_budget_enabled", True))).lower() != "false",
    )


def _load_ui_config(yaml_cfg: dict) -> "UIConfig":
    """Load UIConfig from the 'ui' and 'security' section of config.yaml."""
    u = yaml_cfg.get("ui", {})
    sec = yaml_cfg.get("security", {})
    return UIConfig(
        enabled=str(u.get("enabled", True)).lower() != "false",
        host=u.get("host", "127.0.0.1"),
        port=int(u.get("port", 8000)),
        cors_origins=u.get("cors_origins", ["*"]),
        session_timeout_minutes=int(sec.get("session_timeout_minutes", 60)),
        require_auth=str(sec.get("require_authentication", False)).lower() == "true",
        dev_mode=str(u.get("dev_mode", False)).lower() == "true",
    )


def _load_intelligence_config(yaml_cfg: dict) -> "IntelligenceConfig":
    """Load IntelligenceConfig from the 'intelligence' section of config.yaml."""
    intel = yaml_cfg.get("intelligence", {})
    plan = intel.get("planning", {})
    ctx = intel.get("context", {})
    vision = intel.get("vision", {})
    verif = intel.get("verification", {})

    return IntelligenceConfig(
        planning_enabled=str(plan.get("enabled", True)).lower() != "false",
        planning_max_steps=int(plan.get("max_steps", 20)),
        planning_max_retries=int(plan.get("max_retries", 3)),
        context_max_tokens=int(ctx.get("max_tokens", 8000)),
        context_memory_limit=int(ctx.get("memory_limit", 5)),
        context_observation_limit=int(ctx.get("observation_limit", 10)),
        multimodal_enabled=str(intel.get("multimodal", {}).get("enabled", True)).lower() != "false",
        vision_provider=vision.get("provider", "mock"),
        model_router_enabled=str(intel.get("model_router", {}).get("enabled", True)).lower() != "false",
        verification_required_for_side_effects=str(verif.get("required_for_side_effects", True)).lower() != "false",
        dry_run=str(intel.get("dry_run", False)).lower() == "true",
    )


def _load_integrations_config(yaml_cfg: dict) -> "IntegrationsConfig":
    """Load IntegrationsConfig from the 'integrations' section of config.yaml."""
    integ = yaml_cfg.get("integrations", {})
    mcp = integ.get("mcp", {})
    cb = integ.get("circuit_breaker", {})

    return IntegrationsConfig(
        enabled=str(integ.get("enabled", True)).lower() != "false",
        mcp_enabled=str(mcp.get("enabled", True)).lower() != "false",
        default_timeout_seconds=float(mcp.get("default_timeout_seconds", 30.0)),
        auto_connect_on_startup=str(mcp.get("auto_connect_on_startup", True)).lower() != "false",
        circuit_breaker_failure_threshold=int(cb.get("failure_threshold", 3)),
        circuit_breaker_cooldown_seconds=float(cb.get("cooldown_seconds", 30.0)),
        dry_run=str(integ.get("dry_run", False)).lower() == "true",
        servers=mcp.get("servers", {}),
    )


def _load_tasks_config(yaml_cfg: dict) -> "TasksConfig":
    """Load TasksConfig from the 'tasks' section of config.yaml."""
    t = yaml_cfg.get("tasks", {})
    qh = t.get("quiet_hours", {})
    exec_cfg = t.get("execution", {})

    return TasksConfig(
        enabled=str(t.get("enabled", True)).lower() != "false",
        timezone=t.get("timezone", "UTC"),
        db_path=t.get("db_path", str(ROOT_DIR / "data" / "harma_tasks.db")),
        max_concurrent_tasks=int(exec_cfg.get("max_concurrent_tasks", 3)),
        default_max_runtime_seconds=float(exec_cfg.get("max_runtime_seconds", 300.0)),
        default_max_steps=int(exec_cfg.get("max_steps", 50)),
        min_condition_poll_interval=float(t.get("conditions", {}).get("minimum_poll_interval_seconds", 60.0)),
        dry_run=str(t.get("dry_run", False)).lower() == "true",
        quiet_hours_enabled=str(qh.get("enabled", False)).lower() == "true",
        quiet_hours_start=qh.get("start", "22:00"),
        quiet_hours_end=qh.get("end", "07:00"),
    )


def _load_android_config(yaml_cfg: dict) -> "AndroidConfig":
    """Load AndroidConfig from the 'android' section of config.yaml."""
    a = yaml_cfg.get("android", {})
    trans = a.get("transport", {})
    obs = a.get("observation", {})
    inter = a.get("interaction", {})
    priv = a.get("privacy", {})

    return AndroidConfig(
        enabled=str(a.get("enabled", True)).lower() != "false",
        transport=trans.get("provider", "adb") if isinstance(trans, dict) else "adb",
        adb_path=trans.get("adb_path", "adb") if isinstance(trans, dict) else "adb",
        device_id=trans.get("device", "") if isinstance(trans, dict) else "",
        include_screenshots=str(obs.get("screenshots", True)).lower() != "false",
        action_timeout_seconds=float(inter.get("action_timeout_ms", 15000)) / 1000.0,
        retry_count=int(inter.get("retry_count", 1)),
        save_screenshots=str(priv.get("save_screenshots", False)).lower() == "true",
        detect_secrets=str(priv.get("detect_secrets", True)).lower() != "false",
    )


def _load_voice_config(yaml_cfg: dict) -> "VoiceConfig":
    """Load VoiceConfig from the 'voice' section of config.yaml."""
    v = yaml_cfg.get("voice", {})
    ww = v.get("wake_word", {})
    mic = v.get("microphone", {})
    vad = v.get("vad", {})
    stt = v.get("stt", {})
    tts = v.get("tts", {})
    conv = v.get("conversation_mode", {})
    priv = v.get("privacy", {})

    return VoiceConfig(
        enabled=str(v.get("enabled", True)).lower() != "false",
        wake_word_enabled=str(ww.get("enabled", False)).lower() == "true",
        wake_word_phrase=ww.get("phrase", "hey harma"),
        microphone_device=mic.get("device", "default"),
        microphone_sample_rate=int(mic.get("sample_rate", 16_000)),
        microphone_channels=int(mic.get("channels", 1)),
        vad_enabled=str(vad.get("enabled", True)).lower() != "false",
        vad_silence_timeout_ms=int(vad.get("silence_timeout_ms", 1200)),
        vad_min_speech_ms=int(vad.get("minimum_speech_ms", 250)),
        stt_provider=stt.get("provider", "google"),
        stt_language=stt.get("language", "en-IN"),
        stt_timeout=float(stt.get("timeout", 15.0)),
        tts_provider=tts.get("provider", "pyttsx3"),
        tts_rate=int(tts.get("rate", 175)),
        tts_volume=float(tts.get("volume", 0.95)),
        tts_voice_id=tts.get("voice_id", ""),
        conversation_mode_enabled=str(conv.get("enabled", False)).lower() == "true",
        conversation_inactivity_timeout=float(conv.get("inactivity_timeout_seconds", 30.0)),
        conversation_max_duration=float(conv.get("max_duration_seconds", 600.0)),
        listen_timeout=float(v.get("listen_timeout_seconds", 15.0)),
        save_recordings=str(priv.get("save_recordings", False)).lower() == "true",
        recordings_dir=priv.get("recordings_dir", ""),
    )


# Module-level singleton — import this in other modules
config: HarmaConfig = load_config()
