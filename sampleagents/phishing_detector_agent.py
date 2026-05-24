"""
Phishing Email Detector Agent

A security-focused agent that analyzes emails for phishing indicators
and provides risk scores with detailed red flag analysis.

This agent demonstrates the AI Agent Framework capabilities for:
- Parallel task execution (feature extraction + pattern checking run simultaneously)
- LLM-powered reasoning for nuanced threat analysis
- Self-healing fallback (works with or without an API key)
- Structured security reporting

Usage:
    # Run demo (no API key needed):
    python phishing_detector_agent.py

    # Run with Gemini (live LLM analysis):
    python phishing_detector_agent.py --gemini YOUR_API_KEY

    # Run with OpenRouter/DeepSeek (live LLM analysis):
    python phishing_detector_agent.py --openrouter YOUR_API_KEY

    # Analyze a custom .eml file:
    python phishing_detector_agent.py --eml path/to/email.eml

    # Analyze raw text:
    python phishing_detector_agent.py --text "Urgent! Click here to verify your account..."

    # Programmatic usage:
    from sampleagents.phishing_detector_agent import create_phishing_detector_agent

    agent = create_phishing_detector_agent()  # No API key = simulated mode
    result = agent.run_flow("phishing_detection_workflow", context={
        "email_text": "Your account has been suspended...",
        "email_subject": "Urgent Action Required",
        "email_sender": "security@paypa1.com"
    })
"""

import os
import re
import time
import json
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

# Import from our framework
from framework import (
    Agent,
    Flow,
    FunctionTask,
    tool,
    tool_registry,
)

# ── Optional LLM imports ───────────────────────────────────────────────────────

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    genai = None

# OpenAI-compatible client used for OpenRouter
try:
    from openai import OpenAI as _OpenAI
    OPENROUTER_AVAILABLE = True
except ImportError:
    OPENROUTER_AVAILABLE = False
    _OpenAI = None


# ══════════════════════════════════════════════════════════════════════════════
# DEMO EMAILS  (self-contained, no file needed)
# ══════════════════════════════════════════════════════════════════════════════

DEMO_EMAILS = [
    {
        "label": "Obvious Phishing",
        "subject": "URGENT: Your PayPal account has been SUSPENDED",
        "sender": "support@paypa1-security-alert.com",
        "body": (
            "Dear Valued Customer,\n\n"
            "We have detected suspicious activity on your account. "
            "Your account will be permanently DELETED within 24 hours unless you verify immediately.\n\n"
            "Click here NOW to restore access: http://paypa1-verify.tk/login?ref=urgent\n\n"
            "You must provide your Social Security Number and credit card details to confirm your identity.\n\n"
            "Failure to act will result in legal consequences.\n\n"
            "PayPal Security Team"
        ),
    },
    {
        "label": "Legitimate Email",
        "subject": "Your GitHub pull request was merged",
        "sender": "notifications@github.com",
        "body": (
            "Hi there,\n\n"
            "Your pull request #42 'feat: add dark mode support' was merged into main "
            "by octocat.\n\n"
            "View the pull request: https://github.com/owner/repo/pull/42\n\n"
            "You're receiving this because you authored the pull request.\n"
            "Manage your notification settings at https://github.com/settings/notifications\n\n"
            "GitHub"
        ),
    },
    {
        "label": "Borderline / Suspicious",
        "subject": "You have been selected for an exclusive reward",
        "sender": "rewards@amazon-customer-loyalty.net",
        "body": (
            "Hello Amazon Customer,\n\n"
            "Congratulations! You have been randomly selected to receive a $500 gift card "
            "as part of our annual loyalty program.\n\n"
            "To claim your reward, please confirm your shipping address and payment method "
            "at: http://amazon-rewards-claim.net/gift?id=7829\n\n"
            "This offer expires in 48 hours. Limited to one per household.\n\n"
            "Best regards,\n"
            "Amazon Customer Rewards"
        ),
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# TOOLS
# ══════════════════════════════════════════════════════════════════════════════

@tool(
    name="extract_email_features",
    description="Extract structural features from an email for analysis",
    parameters={
        "subject":  {"type": "string", "description": "Email subject line"},
        "sender":   {"type": "string", "description": "Sender email address"},
        "body":     {"type": "string", "description": "Email body text"},
    },
    tags=["email", "security", "extraction"]
)
def extract_email_features(subject: str, sender: str, body: str) -> Dict[str, Any]:
    """
    Extract structural features from an email.
    Pulls out sender domain, URLs, urgency language, and other signals.
    """
    # ── Sender analysis ───────────────────────────────────────────────────────
    sender_domain = ""
    sender_username = ""
    if "@" in sender:
        parts = sender.split("@")
        sender_username = parts[0]
        sender_domain = parts[1].strip(">").lower()

    # ── URL extraction ────────────────────────────────────────────────────────
    url_pattern = re.compile(
        r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    )
    urls = url_pattern.findall(body)

    parsed_urls = []
    for url in urls:
        try:
            parsed = urlparse(url)
            parsed_urls.append({
                "url": url,
                "domain": parsed.netloc.lower(),
                "scheme": parsed.scheme,
                "is_https": parsed.scheme == "https",
                "tld": parsed.netloc.split(".")[-1].lower() if "." in parsed.netloc else ""
            })
        except Exception:
            parsed_urls.append({"url": url, "domain": "", "scheme": "", "is_https": False, "tld": ""})

    # ── Urgency / pressure language ───────────────────────────────────────────
    urgency_words = [
        "urgent", "immediately", "expires", "suspended", "verify now",
        "act now", "limited time", "click here", "confirm now", "account locked",
        "24 hours", "48 hours", "permanently deleted", "legal consequences",
        "won", "prize", "selected", "congratulations", "free", "claim"
    ]
    body_lower = (subject + " " + body).lower()
    found_urgency = [w for w in urgency_words if w in body_lower]

    # ── Sensitive data requests ───────────────────────────────────────────────
    sensitive_keywords = [
        "social security", "ssn", "credit card", "password", "pin",
        "bank account", "routing number", "date of birth", "passport"
    ]
    found_sensitive = [k for k in sensitive_keywords if k in body_lower]

    # ── Suspicious TLDs ───────────────────────────────────────────────────────
    suspicious_tlds = {"tk", "ml", "ga", "cf", "gq", "xyz", "top", "click", "link", "pw"}
    suspicious_url_tlds = [
        u for u in parsed_urls if u.get("tld") in suspicious_tlds
    ]

    return {
        "sender_domain": sender_domain,
        "sender_username": sender_username,
        "url_count": len(urls),
        "urls": parsed_urls,
        "urgency_words_found": found_urgency,
        "urgency_count": len(found_urgency),
        "sensitive_data_requested": found_sensitive,
        "suspicious_tld_urls": suspicious_url_tlds,
        "body_word_count": len(body.split()),
        "has_html": bool(re.search(r"<[a-z][\s\S]*>", body, re.IGNORECASE)),
        "subject": subject,
        "sender": sender,
    }


@tool(
    name="check_suspicious_patterns",
    description="Check email features against known phishing patterns",
    parameters={
        "features": {"type": "object", "description": "Extracted email features dict"},
    },
    tags=["email", "security", "patterns"]
)
def check_suspicious_patterns(features: Dict[str, Any]) -> Dict[str, Any]:
    """
    Rule-based pattern checker. Produces a list of red flags and a base risk score.
    This runs in parallel with feature extraction and feeds into LLM analysis.
    """
    red_flags = []
    score = 0  # 0–100

    sender_domain = features.get("sender_domain", "")
    urls = features.get("urls", [])
    urgency = features.get("urgency_words_found", [])
    sensitive = features.get("sensitive_data_requested", [])
    suspicious_tlds = features.get("suspicious_tld_urls", [])

    # ── Domain impersonation check ────────────────────────────────────────────
    trusted_brands = ["paypal", "amazon", "google", "microsoft", "apple",
                      "netflix", "bank", "chase", "wellsfargo", "citibank"]
    for brand in trusted_brands:
        if brand in sender_domain and not sender_domain.endswith(f"{brand}.com"):
            red_flags.append(
                f"Domain impersonation: sender uses '{sender_domain}' "
                f"which mimics '{brand}.com'"
            )
            score += 30
            break

    # ── Suspicious TLDs ───────────────────────────────────────────────────────
    if suspicious_tlds:
        for u in suspicious_tlds:
            red_flags.append(
                f"Suspicious TLD in URL: '{u['url']}' uses '.{u['tld']}' "
                f"(common in free/malicious domains)"
            )
            score += 20

    # ── HTTP (not HTTPS) links ─────────────────────────────────────────────────
    http_urls = [u for u in urls if not u.get("is_https")]
    if http_urls:
        red_flags.append(
            f"{len(http_urls)} unencrypted HTTP link(s) found — "
            f"legitimate services use HTTPS"
        )
        score += 15

    # ── Urgency language ──────────────────────────────────────────────────────
    if len(urgency) >= 3:
        red_flags.append(
            f"High-pressure language detected: {', '.join(urgency[:5])}"
        )
        score += 20
    elif len(urgency) >= 1:
        red_flags.append(
            f"Urgency language detected: {', '.join(urgency)}"
        )
        score += 10

    # ── Sensitive data requests ───────────────────────────────────────────────
    if sensitive:
        red_flags.append(
            f"Requests sensitive information: {', '.join(sensitive)}"
        )
        score += 25

    # ── URL domain mismatch ───────────────────────────────────────────────────
    for url_info in urls:
        domain = url_info.get("domain", "")
        for brand in trusted_brands:
            if brand in domain and not domain.endswith(f"{brand}.com"):
                red_flags.append(
                    f"URL domain spoofing: link goes to '{domain}' "
                    f"pretending to be '{brand}.com'"
                )
                score += 25
                break

    # ── No red flags ──────────────────────────────────────────────────────────
    if not red_flags:
        red_flags.append("No obvious rule-based red flags detected")

    # Cap score at 100
    score = min(score, 100)

    # Derive preliminary verdict
    if score >= 70:
        verdict = "HIGH RISK"
    elif score >= 40:
        verdict = "MEDIUM RISK"
    elif score >= 15:
        verdict = "LOW RISK"
    else:
        verdict = "LIKELY SAFE"

    return {
        "red_flags": red_flags,
        "rule_based_score": score,
        "preliminary_verdict": verdict,
        "flags_count": len(red_flags),
    }


@tool(
    name="parse_eml_file",
    description="Parse a .eml file and extract subject, sender, and body",
    parameters={
        "eml_path": {"type": "string", "description": "Path to the .eml file"},
    },
    tags=["email", "parsing", "eml"]
)
def parse_eml_file(eml_path: str) -> Dict[str, Any]:
    """
    Parse a raw .eml file into subject, sender, and body components.
    """
    import email as email_lib

    if not os.path.exists(eml_path):
        raise FileNotFoundError(f".eml file not found: {eml_path}")

    with open(eml_path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()

    msg = email_lib.message_from_string(raw)

    subject = msg.get("Subject", "(no subject)")
    sender = msg.get("From", "(unknown sender)")

    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    body += payload.decode("utf-8", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode("utf-8", errors="replace")

    return {
        "subject": subject,
        "sender": sender,
        "body": body,
        "raw_size": len(raw),
        "source": "eml_file",
        "path": eml_path,
    }


# ══════════════════════════════════════════════════════════════════════════════
# LLM WRAPPERS
# ══════════════════════════════════════════════════════════════════════════════

class GeminiLLM:
    """Thin wrapper around Google Gemini for phishing analysis."""

    def __init__(self, api_key: str, model: str = "gemini-1.5-flash"):
        if not GEMINI_AVAILABLE:
            raise RuntimeError("Install google-generativeai: pip install google-generativeai")
        genai.configure(api_key=api_key)
        self.model_name = model
        self.model = genai.GenerativeModel(
            model_name=model,
            generation_config=genai.GenerationConfig(max_output_tokens=1024, temperature=0.2)
        )

    def analyze(self, prompt: str) -> str:
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"[Gemini error: {e}]"


class OpenRouterLLM:
    """Thin wrapper around OpenRouter (DeepSeek etc.) for phishing analysis."""

    BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self, api_key: str, model: str = "deepseek/deepseek-chat-free"):
        if not OPENROUTER_AVAILABLE:
            raise RuntimeError("Install openai: pip install openai")
        self.model_name = model
        self.client = _OpenAI(api_key=api_key, base_url=self.BASE_URL)

    def analyze(self, prompt: str) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                temperature=0.2,
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"[OpenRouter error: {e}]"


# ══════════════════════════════════════════════════════════════════════════════
# SIMULATED LLM  (fallback — no API key needed)
# ══════════════════════════════════════════════════════════════════════════════

def _simulated_llm_analysis(
    features: Dict[str, Any],
    patterns: Dict[str, Any],
) -> str:
    """
    Rule-based analysis that *mimics* what an LLM would say.
    Used when no API key is provided — keeps the demo self-contained.
    """
    score = patterns.get("rule_based_score", 0)
    verdict = patterns.get("preliminary_verdict", "UNKNOWN")
    flags = patterns.get("red_flags", [])
    sender_domain = features.get("sender_domain", "unknown")
    url_count = features.get("url_count", 0)
    sensitive = features.get("sensitive_data_requested", [])

    lines = [
        f"[SIMULATED ANALYSIS — no API key detected, using rule-based reasoning]\n",
        f"After examining this email, here is my security assessment:\n",
    ]

    if score >= 70:
        lines.append(
            "This email exhibits multiple hallmarks of a phishing attack. "
            f"The sender domain '{sender_domain}' appears to impersonate a trusted brand. "
        )
        if sensitive:
            lines.append(
                f"Most critically, it requests sensitive personal information ({', '.join(sensitive)}), "
                "which legitimate organizations never ask for via email. "
            )
        if url_count > 0:
            lines.append(
                "The embedded links do not lead to the claimed organization's official domain. "
            )
        lines.append(
            "I strongly advise: DO NOT click any links, DO NOT provide any information, "
            "and report this email as phishing immediately."
        )
    elif score >= 40:
        lines.append(
            "This email shows several suspicious characteristics that warrant caution. "
            f"The sender domain '{sender_domain}' is not a verified official domain. "
        )
        lines.append(
            "While not conclusively malicious, the combination of urgency language and "
            "unverified links suggests this could be a phishing or scam attempt. "
            "Verify independently before taking any action."
        )
    elif score >= 15:
        lines.append(
            "This email has minor suspicious indicators but is not strongly characteristic "
            "of phishing. It may be legitimate promotional email or low-risk spam. "
            "Exercise normal caution — do not click links unless you trust the sender."
        )
    else:
        lines.append(
            "This email does not exhibit common phishing indicators. "
            f"The sender domain '{sender_domain}' appears to be a recognized service. "
            "The language is neutral without urgency pressure. It appears to be a "
            "legitimate notification."
        )

    if flags and flags[0] != "No obvious rule-based red flags detected":
        lines.append(f"\nKey indicators identified: {len(flags)} red flag(s) detected.")

    return " ".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# CORE LLM ANALYSIS FUNCTION
# ══════════════════════════════════════════════════════════════════════════════

def _run_llm_analysis(
    ctx: Dict[str, Any],
    llm=None,
) -> Dict[str, Any]:
    """
    Called by the llm_analyze FunctionTask.
    Uses real LLM if available, falls back to simulated analysis.
    """
    features = ctx.get("extract_features_result", {})
    patterns = ctx.get("check_patterns_result", {})

    # ── Build prompt for real LLM ─────────────────────────────────────────────
    prompt = f"""You are a cybersecurity analyst specializing in email phishing detection.

Analyze the following email and the pre-extracted features, then provide a security assessment.

=== EMAIL ===
Subject: {ctx.get('email_subject', '(unknown)')}
From: {ctx.get('email_sender', '(unknown)')}
Body:
{ctx.get('email_body', '(no body)')}

=== PRE-EXTRACTED FEATURES ===
Sender Domain: {features.get('sender_domain', 'unknown')}
URLs Found: {features.get('url_count', 0)}
URL List: {json.dumps([u.get('url') for u in features.get('urls', [])], indent=2)}
Urgency Words: {features.get('urgency_words_found', [])}
Sensitive Data Requested: {features.get('sensitive_data_requested', [])}
Rule-Based Red Flags: {patterns.get('red_flags', [])}
Preliminary Rule Score: {patterns.get('rule_based_score', 0)}/100

=== YOUR TASK ===
1. Validate or challenge the rule-based findings with your own reasoning.
2. Identify any additional subtle phishing indicators the rules may have missed.
3. Provide a concise 3-5 sentence expert analysis.
4. State your final verdict: LIKELY SAFE / LOW RISK / MEDIUM RISK / HIGH RISK / CRITICAL THREAT

Keep your response clear and actionable for a non-technical user."""

    if llm is not None:
        analysis_text = llm.analyze(prompt)
        mode = "live"
        model_name = getattr(llm, "model_name", "unknown")
    else:
        analysis_text = _simulated_llm_analysis(features, patterns)
        mode = "simulated"
        model_name = "rule-based-fallback"

    return {
        "analysis": analysis_text,
        "mode": mode,
        "model": model_name,
    }


# ══════════════════════════════════════════════════════════════════════════════
# REPORT GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

def _generate_report(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Assembles the final structured report from all task results."""
    features = ctx.get("extract_features_result", {})
    patterns = ctx.get("check_patterns_result", {})
    llm_result = ctx.get("llm_analyze_result", {})

    rule_score = patterns.get("rule_based_score", 0)

    # Risk label
    if rule_score >= 70:
        risk_level = "🔴 HIGH RISK"
    elif rule_score >= 40:
        risk_level = "🟠 MEDIUM RISK"
    elif rule_score >= 15:
        risk_level = "🟡 LOW RISK"
    else:
        risk_level = "🟢 LIKELY SAFE"

    return {
        "risk_level": risk_level,
        "risk_score": f"{rule_score}/100",
        "red_flags": patterns.get("red_flags", []),
        "flags_count": patterns.get("flags_count", 0),
        "sender_domain": features.get("sender_domain", "unknown"),
        "urls_found": features.get("url_count", 0),
        "urgency_words": features.get("urgency_words_found", []),
        "sensitive_data_requested": features.get("sensitive_data_requested", []),
        "llm_analysis": llm_result.get("analysis", ""),
        "analysis_mode": llm_result.get("mode", "simulated"),
        "model_used": llm_result.get("model", "rule-based-fallback"),
        "analyzed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "subject": ctx.get("email_subject", ""),
        "sender": ctx.get("email_sender", ""),
    }


# ══════════════════════════════════════════════════════════════════════════════
# AGENT FACTORY
# ══════════════════════════════════════════════════════════════════════════════

def create_phishing_detector_agent(
    gemini_api_key: Optional[str] = None,
    openrouter_api_key: Optional[str] = None,
    model: str = "gemini-1.5-flash",
) -> Agent:
    """
    Create a Phishing Email Detector Agent.

    The agent auto-detects available LLMs. If neither API key is provided,
    it falls back to simulated rule-based analysis so the demo always runs.

    Args:
        gemini_api_key:     Google AI Studio key (or set GOOGLE_API_KEY env var)
        openrouter_api_key: OpenRouter key (or set OPEN_ROUTER_API env var)
        model:              LLM model name (default: gemini-1.5-flash)

    Returns:
        Configured Agent instance ready to run 'phishing_detection_workflow'
    """
    # ── Resolve API keys from env if not passed ───────────────────────────────
    gemini_key = gemini_api_key or os.environ.get("GOOGLE_API_KEY")
    openrouter_key = openrouter_api_key or os.environ.get("OPEN_ROUTER_API")

    # ── Pick LLM (Gemini preferred, then OpenRouter, then simulated) ──────────
    llm = None
    if gemini_key and GEMINI_AVAILABLE:
        try:
            llm = GeminiLLM(api_key=gemini_key, model=model)
        except Exception:
            llm = None
    if llm is None and openrouter_key and OPENROUTER_AVAILABLE:
        try:
            llm = OpenRouterLLM(api_key=openrouter_key)
        except Exception:
            llm = None

    # ── Build Agent ───────────────────────────────────────────────────────────
    agent = Agent(
        name="PhishingDetectorAgent",
        description=(
            "A security agent that analyzes emails for phishing indicators, "
            "produces a risk score, and advises users on safe action."
        )
    )

    flow = agent.create_flow(
        name="phishing_detection_workflow",
        description="Parallel feature extraction + pattern checking → LLM analysis → report",
        max_workers=2,
    )

    # ── Task 1: Extract structural features ──────────────────────────────────
    extract_task = FunctionTask(
        name="extract_features",
        func=lambda ctx: tool_registry.execute(
            "extract_email_features",
            {
                "subject": ctx.get("email_subject", ""),
                "sender":  ctx.get("email_sender", ""),
                "body":    ctx.get("email_body", ""),
            }
        ),
        description="Extract sender domain, URLs, urgency language, sensitive data requests",
        max_retries=1,
    )

    # ── Task 2: Pattern check (runs in PARALLEL with extract_features) ────────
    pattern_task = FunctionTask(
        name="check_patterns",
        func=lambda ctx: tool_registry.execute(
            "check_suspicious_patterns",
            {"features": ctx.get("extract_features_result", {})}
        ),
        description="Match extracted features against known phishing patterns",
    )

    # ── Task 3: LLM analysis (waits for both parallel tasks) ──────────────────
    llm_task = FunctionTask(
        name="llm_analyze",
        func=lambda ctx: _run_llm_analysis(ctx, llm),
        description="LLM-powered security reasoning (or simulated if no API key)",
    )

    # ── Task 4: Final report ───────────────────────────────────────────────────
    report_task = FunctionTask(
        name="generate_report",
        func=_generate_report,
        description="Assemble structured phishing report with risk score and advice",
    )

    # ── Wire the DAG ──────────────────────────────────────────────────────────
    #
    #   extract_features ──┐
    #                      ├──► llm_analyze ──► generate_report
    #   check_patterns ────┘
    #
    # Note: check_patterns depends on extract_features (needs its output),
    #       so they are sequential — but both finish before llm_analyze starts.

    flow.add_tasks(extract_task, pattern_task, llm_task, report_task)
    flow.add_dependency("check_patterns", "extract_features")
    flow.add_dependency("llm_analyze", "check_patterns")
    flow.add_dependency("generate_report", "llm_analyze")

    return agent


# ══════════════════════════════════════════════════════════════════════════════
# PRETTY PRINTER
# ══════════════════════════════════════════════════════════════════════════════

def _print_report(report: Dict[str, Any], label: str = "") -> None:
    """Print a human-readable phishing analysis report to the terminal."""
    SEP = "═" * 62

    print(f"\n{SEP}")
    if label:
        print(f"  📧  {label}")
    print(f"  Subject : {report.get('subject', '(unknown)')}")
    print(f"  From    : {report.get('sender', '(unknown)')}")
    print(SEP)

    print(f"\n  RISK LEVEL  : {report.get('risk_level')}")
    print(f"  RISK SCORE  : {report.get('risk_score')}")
    print(f"  URLs Found  : {report.get('urls_found')}")
    print(f"  Analysis    : {report.get('analysis_mode').upper()} "
          f"({report.get('model_used')})")

    red_flags = report.get("red_flags", [])
    print(f"\n  🚩 RED FLAGS ({len(red_flags)}):")
    for flag in red_flags:
        print(f"     • {flag}")

    urgency = report.get("urgency_words", [])
    if urgency:
        print(f"\n  ⚠️  URGENCY WORDS  : {', '.join(urgency)}")

    sensitive = report.get("sensitive_data_requested", [])
    if sensitive:
        print(f"  🔐 SENSITIVE DATA : {', '.join(sensitive)}")

    analysis = report.get("llm_analysis", "")
    if analysis:
        print(f"\n  🤖 LLM ANALYSIS:")
        # Wrap text at 58 chars for clean terminal output
        words = analysis.split()
        line = "     "
        for word in words:
            if len(line) + len(word) + 1 > 62:
                print(line)
                line = "     " + word
            else:
                line += " " + word
        if line.strip():
            print(line)

    print(f"\n  Analyzed at : {report.get('analyzed_at')}")
    print(SEP)


# ══════════════════════════════════════════════════════════════════════════════
# DEMO RUNNER
# ══════════════════════════════════════════════════════════════════════════════

def run_demo(
    emails: Optional[List[Dict]] = None,
    gemini_api_key: Optional[str] = None,
    openrouter_api_key: Optional[str] = None,
) -> None:
    """
    Run the phishing detector demo.

    With no arguments, analyzes the 3 built-in sample emails (no API key needed).
    """
    emails = emails or DEMO_EMAILS

    print("\n" + "╔" + "═" * 60 + "╗")
    print("║        PHISHING EMAIL DETECTOR AGENT  —  DEMO           ║")
    print("║        AI Agent Framework  |  Sample Agent               ║")
    print("╚" + "═" * 60 + "╝")

    # Detect mode
    gemini_key = gemini_api_key or os.environ.get("GOOGLE_API_KEY")
    openrouter_key = openrouter_api_key or os.environ.get("OPEN_ROUTER_API")
    if gemini_key:
        print(f"\n  ✅  Gemini API key detected — using LIVE LLM analysis")
    elif openrouter_key:
        print(f"\n  ✅  OpenRouter API key detected — using LIVE LLM analysis")
    else:
        print(f"\n  ℹ️   No API key found — running in SIMULATED mode (demo still works!)")
        print(f"       To use live LLM: set GOOGLE_API_KEY or OPEN_ROUTER_API env var\n")

    for i, email_data in enumerate(emails, 1):
        print(f"\n  ── Analyzing email {i}/{len(emails)} ──")
        # Fresh agent per email — avoids DAG state deadlock on re-runs
        agent = create_phishing_detector_agent(
            gemini_api_key=gemini_key,
            openrouter_api_key=openrouter_key,
        )

        result = agent.run_flow(
            "phishing_detection_workflow",
            context={
                "email_subject": email_data.get("subject", ""),
                "email_sender":  email_data.get("sender", ""),
                "email_body":    email_data.get("body", ""),
            }
        )

        if result.success:
            report = result.task_results.get("generate_report")
            if report and report.output:
                _print_report(report.output, label=email_data.get("label", ""))
        else:
            print(f"  ❌ Analysis failed: {result.errors}")

    print("\n  Demo complete. 3 emails analyzed.\n")


# ══════════════════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    import sys

    args = sys.argv[1:]

    # ── No args → run demo ────────────────────────────────────────────────────
    if not args:
        run_demo()
        return

    gemini_key = None
    openrouter_key = None
    eml_path = None
    raw_text = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--gemini" and i + 1 < len(args):
            gemini_key = args[i + 1]; i += 2
        elif arg == "--openrouter" and i + 1 < len(args):
            openrouter_key = args[i + 1]; i += 2
        elif arg == "--eml" and i + 1 < len(args):
            eml_path = args[i + 1]; i += 2
        elif arg == "--text" and i + 1 < len(args):
            raw_text = args[i + 1]; i += 2
        else:
            i += 1

    # ── .eml file analysis ────────────────────────────────────────────────────
    if eml_path:
        parsed = tool_registry.execute("parse_eml_file", {"eml_path": eml_path})
        emails = [{
            "label": f"From file: {eml_path}",
            "subject": parsed.get("subject", ""),
            "sender":  parsed.get("sender", ""),
            "body":    parsed.get("body", ""),
        }]
        run_demo(emails=emails, gemini_api_key=gemini_key, openrouter_api_key=openrouter_key)
        return

    # ── Raw text analysis ─────────────────────────────────────────────────────
    if raw_text:
        emails = [{
            "label": "Custom Input",
            "subject": "(raw text input)",
            "sender":  "(unknown)",
            "body":    raw_text,
        }]
        run_demo(emails=emails, gemini_api_key=gemini_key, openrouter_api_key=openrouter_key)
        return

    # ── API key only → run demo with live LLM ─────────────────────────────────
    run_demo(gemini_api_key=gemini_key, openrouter_api_key=openrouter_key)


if __name__ == "__main__":
    main()
