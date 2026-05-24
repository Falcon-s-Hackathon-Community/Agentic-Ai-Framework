---

## Understanding the Daily Traffic Alert Agent

### A Simple Case Study

---

## 1. The Problem in Simple Terms

Every morning, you need to leave home on time to reach college or work.
But traffic changes every day — some days it takes 30 minutes, some days 60.

**Without the agent:**
1. You wake up and manually open Google Maps
2. You check the current traffic to your destination
3. You calculate when to leave
4. You set a reminder yourself

You do this **every single day, manually**.

---

## 2. The Agent Way

With the Traffic Alert Agent:

➡️ You set up your details **once** (home, destination, departure time)
➡️ The agent **automatically checks traffic every day**
➡️ It **alerts you at the right time** before you need to leave

No manual checking. No forgetting. It just works.

---

## 3. What Is This Agent Actually Doing?

It is:
- Following a **fixed set of steps** every day
- Using the **Google Maps API** to get real traffic data
- Calculating your leave time based on current conditions
- Printing a formatted alert for you

Think of it as a **smart alarm clock** that checks traffic before it rings.

---

## 4. The Three Steps (DAG)

The agent follows exactly **3 steps in order**, every time it runs:

```
Load Config → Get Traffic → Format Report
```

### Step 1: Load Config
Reads your saved preferences from `traffic_config.json`
- Your home address
- Your destination
- Your departure time
- How many minutes before to alert you

### Step 2: Get Traffic
Calls Google Maps Distance Matrix API with your addresses.
Gets back:
- Normal travel time (no traffic)
- Current travel time (with live traffic)
- Delay in minutes
- Traffic status (🟢 Light / 🟡 Moderate / 🔴 Heavy)

**If no API key is found** → runs in Demo Mode with simulated realistic data.
The demo still works perfectly. No API key is required to try it.

### Step 3: Format Report
Takes the traffic data and builds a clean, readable alert:
```
╔══════════════════════════════════════════╗
       🚗  DAILY TRAFFIC ALERT
╚══════════════════════════════════════════╝
  ⏰  Alert time    : 60 min before departure
  🕐  Departure     : 09:00
  📍  From          : Koregaon Park, Pune
  🏢  To            : Hinjewadi Phase 1, Pune
  📏  Distance      : 18.3 km
  🕑  Normal time   : 28 mins
  🚦  With traffic  : 52 mins
  🔴 Heavy traffic
  ✅  Recommended leave by: 08:03 AM
```

---

## 5. Mapping to Framework Terms

| What the Agent Does         | Framework Term  |
|-----------------------------|-----------------|
| Reads your config file      | Tool            |
| Calls Google Maps API       | Tool            |
| Formats the alert message   | Tool            |
| The order: step 1→2→3       | DAG             |
| Running all steps together  | Flow            |
| The overall agent system    | Agent           |

---

## 6. The Self-Healing Fallback (Key Feature)

This agent was designed so the **demo always works**, even without a real API key.

| Situation                        | What Happens                          |
|----------------------------------|---------------------------------------|
| Google Maps API key present      | Real live traffic data from Google    |
| No API key / API key = "demo"    | Simulated realistic traffic data      |
| `googlemaps` library not installed | Same simulated fallback              |

The simulated data even changes based on **time of day** — it gives heavier
traffic during morning and evening rush hours, lighter traffic at night.
This makes the demo feel real and meaningful.

---

## 7. State Persistence (Why `traffic_config.json` Exists)

The agent saves your preferences to a local JSON file.
This means:
- You set up your details **once**
- Every time the agent runs after that, it **remembers** your settings
- No database, no cloud, no account — just a simple local file

This is what the framework calls **state persistence**.

---

## 8. How to Run It

```bash
# Set PYTHONPATH first (required)
export PYTHONPATH=$(pwd)          # Linux/macOS
$env:PYTHONPATH = (Get-Location).Path  # Windows PowerShell

# Step 1: Set up your preferences (run once)
python sampleagents/traffic_agent.py --setup

# Step 2: One-time check right now
python sampleagents/traffic_agent.py --check

# Step 3: Run daily scheduler (keeps running in background)
python sampleagents/traffic_agent.py --run
```

**No API key needed for demo** — just run `--check` after `--setup`.

---

## 9. Final One-Line Understanding

> You tell the agent your home, destination, and departure time once —
> and every day it automatically checks live traffic and tells you
> exactly when to leave.

---
