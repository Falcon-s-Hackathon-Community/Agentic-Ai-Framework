---

## Understanding the Phishing Email Detector Agent

### A Simple Case Study

---

## 1. The Problem in Simple Terms

Phishing emails are fake emails designed to trick you into:
- Clicking malicious links
- Giving away passwords or personal information
- Believing a trusted brand (PayPal, Amazon, Google) is contacting you

**Without the agent:**
1. You receive a suspicious email
2. You read it and try to judge if it looks fake
3. You manually check the sender address
4. You google whether the links are safe
5. You decide — often incorrectly

This is slow, unreliable, and most people get it wrong.

---

## 2. The Agent Way

With the Phishing Detector Agent:

➡️ You give it the email (text, `.eml` file, or run the built-in demo)
➡️ The agent **automatically extracts suspicious signals**
➡️ It **scores the email from 0 to 100** for phishing risk
➡️ It **lists every red flag** it found
➡️ An LLM reasons about it like a **cybersecurity analyst** and gives advice

No manual checking. Clear verdict. Actionable advice.

---

## 3. What Makes This More Agentic Than Other Sample Agents?

The Phishing Detector is a step further:

- The **LLM actually reasons** about the email — it does not just generate text,
  it weighs evidence and forms a judgment
- The LLM can **challenge or confirm** the rule-based findings
- It can catch **subtle signals** that fixed rules miss
  (e.g. overly formal language, unusual greeting style, tone mismatch)

The rules find obvious red flags. The LLM finds the ones rules cannot.

---

## 4. The Four Steps (DAG)

```
extract_features → check_patterns → llm_analyze → generate_report
```

### Step 1: Extract Features
Pulls structural information out of the email:
- Sender domain (e.g. `paypa1-security-alert.com`)
- All URLs found in the body
- Whether links use HTTP or HTTPS
- URL domain extensions (`.tk`, `.ml`, `.xyz` are suspicious)
- Urgency words (`urgent`, `click here`, `suspended`, `expires`)
- Requests for sensitive data (`password`, `credit card`, `SSN`)

### Step 2: Check Patterns (Rule-Based Scoring)
Compares extracted features against known phishing patterns.
Produces a **risk score from 0–100** and a list of red flags.

| Pattern Detected                        | Score Added |
|-----------------------------------------|-------------|
| Domain impersonation (paypa1 vs paypal) | +30         |
| Suspicious TLD in URL (.tk, .ml, etc.)  | +20         |
| HTTP links instead of HTTPS             | +15         |
| High-pressure urgency language (3+)     | +20         |
| Sensitive data requested                | +25         |
| URL domain spoofing                     | +25         |

Score is capped at 100.

### Step 3: LLM Analysis
Takes everything from Steps 1 and 2 and sends it to an LLM
with a prompt that says: *"You are a cybersecurity analyst. Review this email
and its extracted features. What is your expert assessment?"*

The LLM:
- Validates or challenges the rule-based score
- Finds subtle signals the rules missed
- Explains its reasoning in plain language
- States a final verdict: LIKELY SAFE / LOW RISK / MEDIUM RISK / HIGH RISK / CRITICAL THREAT

**If no API key is available** → a smart simulated analysis runs instead,
using the rule scores to generate a realistic advisory. The demo always works.

### Step 4: Generate Report
Assembles everything into a clean structured output:
```
  RISK LEVEL  : 🔴 HIGH RISK
  RISK SCORE  : 85/100
  URLs Found  : 1
  Analysis    : SIMULATED (rule-based-fallback)

  🚩 RED FLAGS (4):
     • Domain impersonation: sender uses 'paypa1-security-alert.com'
       which mimics 'paypal.com'
     • Suspicious TLD in URL: uses '.tk' (common in malicious domains)
     • High-pressure language: urgent, suspended, deleted, verify now
     • Requests sensitive information: social security, credit card
```

---

## 5. Mapping to Framework Terms

| What the Agent Does                      | Framework Term  |
|------------------------------------------|-----------------|
| Pull URLs, sender, urgency words         | Tool            |
| Score against phishing patterns          | Tool            |
| Parse a `.eml` file into readable text   | Tool            |
| LLM reasoning step                       | FunctionTask    |
| The order: extract→check→analyze→report  | DAG             |
| Running all steps together               | Flow            |
| The overall agent system                 | Agent           |

---

## 6. The Three Demo Emails (No Setup Needed)

The agent ships with 3 built-in sample emails so anyone can run it instantly:

| Email                  | Expected Result     | What It Tests                        |
|------------------------|---------------------|--------------------------------------|
| PayPal suspension fake | 🔴 HIGH RISK        | Domain spoofing + sensitive data ask |
| GitHub PR merged       | 🟢 LIKELY SAFE      | Legitimate notification pattern      |
| Amazon reward claim    | 🟠 MEDIUM RISK      | Borderline scam language + bad URL   |

These three together demonstrate the full spectrum of the agent's judgment —
from obvious phishing to clean legitimate email to the tricky middle ground.

---

## 7. Dual LLM Support (Gemini + OpenRouter)

The agent supports two LLM providers so it works for anyone:

| Provider       | Why It's Included                                  |
|----------------|----------------------------------------------------|
| Google Gemini  | Easy free API key from Google AI Studio            |
| OpenRouter     | Free DeepSeek access, popular alternative          |
| Neither        | Simulated fallback — demo runs with zero setup     |

The agent auto-detects which key is available and picks the right provider.
You never need to configure this manually.

---

## 8. Input Modes

The agent accepts emails in three different ways:

```bash
# Mode 1: Built-in demo (no input needed)
python sampleagents/phishing_detector_agent.py

# Mode 2: Analyze a raw text string
python sampleagents/phishing_detector_agent.py --text "Urgent! Your account is suspended..."

# Mode 3: Analyze a real .eml file
python sampleagents/phishing_detector_agent.py --eml path/to/email.eml

# Mode 4: Use with live Gemini LLM
python sampleagents/phishing_detector_agent.py --gemini YOUR_API_KEY

# Mode 5: Use with live OpenRouter/DeepSeek
python sampleagents/phishing_detector_agent.py --openrouter YOUR_API_KEY
```

---

## 9. Final One-Line Understanding

> You give the agent an email — it automatically extracts suspicious signals,
> scores the phishing risk from 0 to 100, lists every red flag,
> and an LLM explains exactly why it is dangerous and what you should do.

---
