"""
Daily Traffic Alert Agent

An agent that checks travel time from home to work/college every day,
and alerts the user 1 hour (or custom time) before their departure.

Usage:
    # First run - sets up your preferences interactively
    python traffic_agent.py --setup

    # Run the daily scheduler (keeps running in background)
    python traffic_agent.py --run

    # One-time check right now
    python traffic_agent.py --check

    # Or use in code:
    from sampleagents.traffic_agent import create_traffic_agent
    agent = create_traffic_agent(api_key="your-google-maps-api-key")
    result = agent.run_flow("traffic_check_flow", context={...})

Demo (no API key needed):
    python traffic_agent.py --setup   # enter any fake addresses
    python traffic_agent.py --check   # runs with simulated traffic data

Real usage:
    pip install googlemaps schedule
    Get a free Google Maps API key at: https://console.cloud.google.com/
    Enable: "Distance Matrix API"
    Set env var: GOOGLE_MAPS_API_KEY=your_key_here
"""

import os
import json
import time
import datetime
from typing import Any, Dict, Optional

# Import from our framework
from framework import (
    Agent,
    FunctionTask,
    tool,
    tool_registry,
    LogLevel,
    setup_logging,
)

# Google Maps support
try:
    import googlemaps
    GMAPS_AVAILABLE = True
except ImportError:
    GMAPS_AVAILABLE = False
    googlemaps = None

# Schedule support
try:
    import schedule
    SCHEDULE_AVAILABLE = True
except ImportError:
    SCHEDULE_AVAILABLE = False
    schedule = None


# =============================================================================
# CONFIG FILE PATH
# =============================================================================

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "traffic_config.json")


# =============================================================================
# TOOLS
# =============================================================================

@tool(
    name="load_user_config",
    description="Load saved user preferences (home, destination, departure time)",
    parameters={},
    tags=["config", "setup"]
)
def load_user_config() -> Dict[str, Any]:
    """
    Load user config from traffic_config.json.

    Returns:
        Dictionary with home, destination, departure_time, notify_minutes_before
    """
    if not os.path.exists(CONFIG_FILE):
        return {"configured": False}

    with open(CONFIG_FILE, "r") as f:
        config = json.load(f)

    config["configured"] = True
    return config


@tool(
    name="save_user_config",
    description="Save user preferences to config file",
    parameters={
        "home":                   {"type": "string", "description": "Home address"},
        "destination":            {"type": "string", "description": "Work or college address"},
        "departure_time":         {"type": "string", "description": "Departure time e.g. '09:00'"},
        "notify_minutes_before":  {"type": "integer", "description": "How many minutes before departure to alert"}
    },
    tags=["config", "setup"]
)
def save_user_config(
    home: str,
    destination: str,
    departure_time: str,
    notify_minutes_before: int = 60
) -> Dict[str, Any]:
    """
    Save user preferences to traffic_config.json.

    Returns:
        Saved config dictionary
    """
    config = {
        "home": home,
        "destination": destination,
        "departure_time": departure_time,
        "notify_minutes_before": notify_minutes_before
    }

    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

    print(f"\n✅ Config saved to {CONFIG_FILE}")
    return config


def _mock_travel_time(origin: str, destination: str) -> Dict[str, Any]:
    """
    Returns fake but realistic traffic data for demo purposes.
    Used when no real API key is available — just like test.pdf is a fake doc.
    Simulates different traffic conditions based on current hour.
    """
    import random
    now  = datetime.datetime.now()
    hour = now.hour

    # Simulate rush hour (8-10am, 5-7pm = heavy traffic)
    if 8 <= hour <= 10 or 17 <= hour <= 19:
        normal_mins  = 28
        traffic_mins = random.randint(45, 65)
        status       = "🔴 Heavy traffic (demo)"
    elif 11 <= hour <= 16:
        normal_mins  = 28
        traffic_mins = random.randint(32, 42)
        status       = "🟡 Moderate traffic (demo)"
    else:
        normal_mins  = 28
        traffic_mins = random.randint(28, 33)
        status       = "🟢 Light traffic (demo)"

    delay = traffic_mins - normal_mins

    return {
        "origin":           origin,
        "destination":      destination,
        "distance":         "18.3 km (demo)",
        "duration_normal":  f"{normal_mins} mins",
        "duration_traffic": f"{traffic_mins} mins",
        "delay_minutes":    delay,
        "traffic_status":   status,
        "checked_at":       now.strftime("%Y-%m-%d %H:%M:%S"),
        "demo_mode":        True
    }


@tool(
    name="get_travel_time",
    description="Get live travel time between two addresses using Google Maps",
    parameters={
        "origin":      {"type": "string", "description": "Starting address"},
        "destination": {"type": "string", "description": "Destination address"},
        "api_key":     {"type": "string", "description": "Google Maps API key (pass 'demo' to use mock data)"}
    },
    tags=["traffic", "maps", "travel"]
)
def get_travel_time(origin: str, destination: str, api_key: str) -> Dict[str, Any]:
    """
    Calls Google Maps Distance Matrix API to get real-time travel duration.
    If api_key is 'demo' or missing, returns realistic mock data instead.

    Args:
        origin:      Home address
        destination: Work/college address
        api_key:     Google Maps API key (or 'demo' for mock mode)

    Returns:
        Dictionary with duration, distance, and traffic status
    """
    # ---- DEMO MODE (no real API key needed) ----
    if not api_key or api_key == "demo" or not GMAPS_AVAILABLE:
        print("ℹ️  Running in DEMO MODE — using simulated traffic data.")
        return _mock_travel_time(origin, destination)

    # ---- REAL MODE ----
    client = googlemaps.Client(key=api_key)
    now    = datetime.datetime.now()

    result = client.distance_matrix(
        origins=[origin],
        destinations=[destination],
        mode="driving",
        departure_time=now,
        traffic_model="best_guess"
    )

    element = result["rows"][0]["elements"][0]

    if element["status"] != "OK":
        raise ValueError(f"Google Maps error: {element['status']}")

    duration_normal  = element["duration"]["text"]
    duration_traffic = element.get("duration_in_traffic", {}).get("text", duration_normal)
    distance         = element["distance"]["text"]

    def parse_minutes(text: str) -> int:
        total = 0
        if "hour" in text:
            parts = text.split()
            for i, p in enumerate(parts):
                if "hour" in p:
                    total += int(parts[i - 1]) * 60
                if "min" in p:
                    total += int(parts[i - 1])
        elif "min" in text:
            total = int(text.split()[0])
        return total

    normal_mins  = parse_minutes(duration_normal)
    traffic_mins = parse_minutes(duration_traffic)
    delay_mins   = traffic_mins - normal_mins

    if delay_mins <= 5:
        traffic_status = "🟢 Light traffic"
    elif delay_mins <= 15:
        traffic_status = "🟡 Moderate traffic"
    else:
        traffic_status = "🔴 Heavy traffic"

    return {
        "origin":           origin,
        "destination":      destination,
        "distance":         distance,
        "duration_normal":  duration_normal,
        "duration_traffic": duration_traffic,
        "delay_minutes":    delay_mins,
        "traffic_status":   traffic_status,
        "checked_at":       now.strftime("%Y-%m-%d %H:%M:%S"),
        "demo_mode":        False
    }


@tool(
    name="format_traffic_report",
    description="Format the traffic data into a readable alert message",
    parameters={
        "travel_data":      {"type": "object", "description": "Output from get_travel_time"},
        "departure_time":   {"type": "string",  "description": "User's planned departure time e.g. '09:00'"},
        "notify_minutes":   {"type": "integer", "description": "Minutes before departure this alert is for"}
    },
    tags=["traffic", "report", "formatting"]
)
def format_traffic_report(
    travel_data: Dict[str, Any],
    departure_time: str,
    notify_minutes: int = 60
) -> Dict[str, Any]:
    """
    Build a human-readable traffic alert.

    Returns:
        Dictionary with formatted message and recommended leave time
    """
    # Calculate recommended leave time
    dep_hour, dep_min  = map(int, departure_time.split(":"))
    dep_dt             = datetime.datetime.now().replace(hour=dep_hour, minute=dep_min, second=0)
    traffic_mins       = int(travel_data["duration_traffic"].split()[0]) if "min" in travel_data["duration_traffic"] else 30
    leave_dt           = dep_dt - datetime.timedelta(minutes=traffic_mins + 5)  # 5 min buffer

    message = f"""
╔══════════════════════════════════════════╗
       🚗  DAILY TRAFFIC ALERT
╚══════════════════════════════════════════╝

  ⏰  Alert time    : {notify_minutes} min before your departure
  🕐  Departure     : {departure_time}
  📍  From          : {travel_data['origin']}
  🏢  To            : {travel_data['destination']}

  📏  Distance      : {travel_data['distance']}
  🕑  Normal time   : {travel_data['duration_normal']}
  🚦  With traffic  : {travel_data['duration_traffic']}
  {travel_data['traffic_status']}

  ✅  Recommended leave by: {leave_dt.strftime("%I:%M %p")}

  Checked at: {travel_data['checked_at']}
══════════════════════════════════════════
"""

    print(message)

    return {
        "message":              message,
        "recommended_leave_at": leave_dt.strftime("%H:%M"),
        "traffic_status":       travel_data["traffic_status"],
        "duration_with_traffic": travel_data["duration_traffic"]
    }


# =============================================================================
# AGENT FACTORY
# =============================================================================

def create_traffic_agent(api_key: Optional[str] = None) -> Agent:
    """
    Create the Daily Traffic Alert Agent.

    Args:
        api_key: Google Maps API key (or set GOOGLE_MAPS_API_KEY env var)

    Returns:
        Configured Agent instance
    """
    api_key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY") or "demo"

    if api_key == "demo":
        print("ℹ️  No GOOGLE_MAPS_API_KEY found — running in DEMO MODE with simulated data.\n"
              "   To use real traffic data, set: GOOGLE_MAPS_API_KEY=your_key\n")

    agent = Agent(
        name="DailyTrafficAgent",
        description="Checks live traffic from home to work/college and alerts before departure"
    )

    flow = agent.create_flow(
        name="traffic_check_flow",
        description="Load config → get live traffic → format and print alert",
        max_workers=1
    )

    # Task 1: Load saved config
    load_task = FunctionTask(
        name="load_config",
        func=lambda ctx: tool_registry.execute("load_user_config", {}),
        description="Load user home/destination/time preferences"
    )

    # Task 2: Get live traffic from Google Maps
    traffic_task = FunctionTask(
        name="get_traffic",
        func=lambda ctx: tool_registry.execute(
            "get_travel_time",
            {
                "origin":      ctx.get("load_config_result", {}).get("home"),
                "destination": ctx.get("load_config_result", {}).get("destination"),
                "api_key":     api_key
            }
        ),
        description="Fetch real-time travel duration from Google Maps",
        max_retries=2
    )

    # Task 3: Format and print the report
    report_task = FunctionTask(
        name="format_report",
        func=lambda ctx: tool_registry.execute(
            "format_traffic_report",
            {
                "travel_data":    ctx.get("get_traffic_result", {}),
                "departure_time": ctx.get("load_config_result", {}).get("departure_time", "09:00"),
                "notify_minutes": ctx.get("load_config_result", {}).get("notify_minutes_before", 60)
            }
        ),
        description="Format traffic data into a readable alert"
    )

    flow.add_tasks(load_task, traffic_task, report_task)
    flow.add_dependency("get_traffic",    "load_config")
    flow.add_dependency("format_report",  "get_traffic")

    return agent


# =============================================================================
# SETUP WIZARD (first-time use)
# =============================================================================

def run_setup():
    """
    Interactive setup — asks user for their details and saves to config.
    Run this once before using the agent.
    """
    print("\n" + "=" * 50)
    print("  🚗  TRAFFIC AGENT — FIRST TIME SETUP")
    print("=" * 50)
    print("This will save your preferences to traffic_config.json\n")

    home        = input("📍 Your home address (e.g. 'Koregaon Park, Pune'): ").strip()
    destination = input("🏢 Your work/college address (e.g. 'Hinjewadi Phase 1, Pune'): ").strip()

    print("\n⏰ What time do you usually leave? (24hr format)")
    departure   = input("   Departure time (e.g. 09:00 or 08:30): ").strip()

    print("\n🔔 How many minutes before departure should I alert you?")
    notify_str  = input("   Minutes before (default 60): ").strip()
    notify      = int(notify_str) if notify_str.isdigit() else 60

    tool_registry.execute("save_user_config", {
        "home":                  home,
        "destination":           destination,
        "departure_time":        departure,
        "notify_minutes_before": notify
       })
 
    print(f"\n✅ All set! The agent will alert you at "
          f"{_calc_alert_time(departure, notify)} every day.")
    print("   Run with:  python sampleagents/traffic_agent.py --run\n")
 

def _calc_alert_time(departure_time: str, notify_minutes: int) -> str:
    """Calculate what time the alert will fire."""
    h, m     = map(int, departure_time.split(":"))
    dep      = datetime.datetime.now().replace(hour=h, minute=m, second=0)
    alert    = dep - datetime.timedelta(minutes=notify_minutes)
    return alert.strftime("%H:%M")


# =============================================================================
# SCHEDULER (runs daily at the right time)
# =============================================================================

def run_scheduler(api_key: Optional[str] = None):
    """
    Start the daily scheduler. Keeps running and fires alert at the right time.
    Leave this running in the background (or in a terminal).
    """
    if not SCHEDULE_AVAILABLE:
        print("❌ 'schedule' not installed. Run: pip install schedule")
        return

    # Load config to find alert time
    config = tool_registry.execute("load_user_config", {})
    if not config.get("configured"):
        print("❌ Not configured yet! Run: python traffic_agent.py --setup")
        return

    departure       = config["departure_time"]
    notify_minutes  = config.get("notify_minutes_before", 60)
    alert_time      = _calc_alert_time(departure, notify_minutes)

    print(f"\n🚗 Traffic Agent running...")
    print(f"   Will alert you daily at {alert_time} (your departure: {departure})")
    print(f"   Press Ctrl+C to stop.\n")

    agent = create_traffic_agent(api_key=api_key)

    def daily_job():
        print(f"\n⏰ Running scheduled traffic check at {datetime.datetime.now().strftime('%H:%M')}...")
        try:
            agent.run_flow("traffic_check_flow", context={})
        except Exception as e:
            print(f"❌ Error during traffic check: {e}")

    schedule.every().day.at(alert_time).do(daily_job)

    # Run once immediately so you can see it working right away
    print("▶️  Running once now so you can see it works...\n")
    daily_job()

    while True:
        schedule.run_pending()
        time.sleep(30)


# =============================================================================
# DEMO / ONE-TIME CHECK
# =============================================================================

def run_once(api_key: Optional[str] = None):
    """Run a single traffic check right now."""
    config = tool_registry.execute("load_user_config", {})
    if not config.get("configured"):
        print("❌ Not configured yet! Run: python traffic_agent.py --setup")
        return

    api_key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        print("❌ Google Maps API key missing. Set GOOGLE_MAPS_API_KEY env var.")
        return

    agent  = create_traffic_agent(api_key=api_key)
    result = agent.run_flow("traffic_check_flow", context={})

    print(f"\nFlow status  : {result.status.value}")
    print(f"Success      : {result.success}")
    print(f"Time taken   : {result.execution_time:.2f}s")

    return result


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    import sys

    args = sys.argv[1:]

    if not args or "--help" in args or "-h" in args:
        print("""
🚗  Daily Traffic Alert Agent
==============================
Commands:
python sampleagents/traffic_agent.py --setup    Set up your preferences
python sampleagents/traffic_agent.py --run      Start daily scheduler
python sampleagents/traffic_agent.py --check    One-time traffic check

Environment variable:
  GOOGLE_MAPS_API_KEY=your_key_here

Get a free API key: https://console.cloud.google.com/
Enable: Distance Matrix API
        """)
        return

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "demo")

    if "--setup" in args:
        run_setup()

    elif "--run" in args:
        run_scheduler(api_key=api_key)

    elif "--check" in args:
        run_once(api_key=api_key)

    else:
        print(f"Unknown argument: {args[0]}")
        print("Run with --help to see available commands.")


if __name__ == "__main__":
    main()
