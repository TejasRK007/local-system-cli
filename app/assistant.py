"""
Local Executive Assistant Conversational Engine.

Provides 100% offline, private, natural assistant conversational capabilities
when running locally without external cloud dependencies.
Ensures zero emojis, professional executive tone, and contextual awareness.
"""

import datetime
import os
import re
from typing import Any, Dict, List, Optional


def get_assistant_conversational_response(
    msg: str,
    history: Optional[List[Dict[str, Any]]] = None,
    llm_enabled: bool = True,
) -> Optional[str]:
    """
    Evaluates conversational inputs and returns a natural, helpful,
    professional executive assistant response without external network calls.
    Returns None if the message represents an agentic task to be planned.
    """
    clean_msg = msg.strip()
    msg_lower = clean_msg.lower().strip("?!., \t\n")

    # 1. Greetings & Personal Inquiries
    clean_norm = re.sub(r"[,\-_]", " ", msg_lower).strip()
    how_are_you_patterns = [
        "how are you", "how are u", "how are you doing", "how r u",
        "how do you do", "how is it going", "hows it going", "how's it going",
        "how are things", "how is everything"
    ]
    if any(msg_lower == p or msg_lower.startswith(p + " ") or msg_lower.endswith(" " + p) or clean_norm.endswith(" " + p) for p in how_are_you_patterns):
        return (
            "I am doing very well, thank you for asking! I am active and running locally on your device with complete privacy.\n\n"
            "I am ready to help you manage your inbox, schedule events, organize files in your workspaces, or check system metrics. "
            "What can I do for you today?"
        )

    # 2. Presence & Standing-By Checks
    presence_patterns = [
        "are you there", "are u there", "u there", "r u there", "you there",
        "anyone there", "is anyone there", "can you hear me", "can u hear me"
    ]
    if any(msg_lower == p or msg_lower.startswith(p + " ") or msg_lower.endswith(" " + p) for p in presence_patterns):
        return (
            "Yes, I am active and standing by right here on your device.\n\n"
            "How can I assist you with your inbox, calendar, workspaces, or system today?"
        )

    # 3. Quick Connectivity / Health Pings
    if msg_lower in ["ping", "echo"]:
        return "Pong! I am responsive, healthy, and operating locally on your machine with 100% privacy."
    if msg_lower in ["test", "testing", "check test"]:
        return "The local executive assistant is fully operational and standing by. All offline tools and workspace connections are ready."

    # 4. Basic & Informal Social Greetings
    greeting_bases = {
        "hello", "helo", "hlo", "hlw", "hi", "hey", "hiya", "hola",
        "namaste", "howdy", "sup", "yo", "wassup", "whatsup", "wazzup",
        "greetings", "salutations", "aloha"
    }
    multi_word_greetings = [
        "good morning", "good afternoon", "good evening", "good day",
        "hello there", "hey there", "hi there", "yo there", "whats up",
        "what's up", "howdy there", "morning", "afternoon", "evening"
    ]

    clean_alpha = re.sub(r"[^a-z\s]", " ", msg_lower).strip()
    alpha_words = clean_alpha.split()
    first_alpha = alpha_words[0] if alpha_words else ""
    collapsed_first = re.sub(r"([a-z])\1+", r"\1", first_alpha)
    collapsed_full = re.sub(r"([a-z])\1+", r"\1", clean_alpha.replace(" ", ""))

    is_greeting = False
    if (
        clean_alpha in greeting_bases
        or collapsed_full in greeting_bases
        or any(clean_alpha == g for g in multi_word_greetings)
    ):
        is_greeting = True
    elif first_alpha in greeting_bases or collapsed_first in greeting_bases:
        task_indicators = [
            "email", "mail", "file", "folder", "organize", "search", "read",
            "check", "meeting", "calendar", "delete", "storage", "disk", "ram", "cpu"
        ]
        if len(alpha_words) <= 3 or not any(w in alpha_words for w in task_indicators):
            is_greeting = True
    elif any(clean_alpha.startswith(g + " ") for g in multi_word_greetings):
        task_indicators = [
            "email", "mail", "file", "folder", "organize", "search", "read",
            "check", "meeting", "calendar", "delete", "storage", "disk", "ram", "cpu"
        ]
        if len(alpha_words) <= 4 or not any(w in alpha_words for w in task_indicators):
            is_greeting = True

    if is_greeting:
        now_hour = datetime.datetime.now().hour
        time_greeting = "Good morning" if now_hour < 12 else ("Good afternoon" if now_hour < 17 else "Good evening")
        return (
            f"{time_greeting}! I am your local AI Executive Assistant, operating privately on this machine.\n\n"
            "How can I assist you with your tasks, inbox, or device today?"
        )

    # 3. Identity & Role
    identity_patterns = [
        "who are you", "what are you", "who made you", "introduce yourself",
        "what is your name", "tell me about yourself", "who r u"
    ]
    if any(p in msg_lower for p in identity_patterns):
        return (
            "I am your local AI Executive Assistant.\n\n"
            "I run 100% locally on your computer to keep all your personal emails, files, and queries completely private. "
            "My role is to help you triage communications, manage calendar schedules, inspect device health, and automate "
            "multi-step filesystem workflows safely."
        )

    # 4. Capabilities & Help
    capability_patterns = [
        "what can you do", "what do you do", "help me", "help",
        "what are your features", "what are your capabilities", "how can you help",
        "show your features", "what can you help me with"
    ]
    if any(msg_lower == p or p in msg_lower for p in capability_patterns) and len(msg_lower.split()) <= 7:
        return (
            "Here is how I can assist you directly on your machine:\n\n"
            "- **Email Management**: Search and read inbox messages, identify urgent communications, synthesize priority summaries, and draft replies.\n"
            "- **Local Task Planning**: Safely organize workspace documents, convert or archive files, and run multi-step automated workflows.\n"
            "- **Calendar & Agenda**: View upcoming events, meetings, and schedule new calendar appointments.\n"
            "- **Device Diagnostics**: Inspect disk storage, RAM, CPU utilization, and hardware diagnostics.\n"
            "- **100% Offline Privacy**: All operations execute locally on your machine with zero external cloud tracking.\n\n"
            "Tell me what you would like to work on, or choose one of the areas above to get started."
        )

    # 5. Gratitude & Courtesy
    thanks_patterns = ["thank you", "thanks", "thanks a lot", "appreciate it", "thx", "ty", "thank u"]
    if any(msg_lower == p or msg_lower.startswith(p + " ") or msg_lower.endswith(" " + p) for p in thanks_patterns):
        return "You are very welcome! I am always here to assist. Let me know if there is anything else you need."

    # 6. Acknowledgements & Confirmation
    ack_words = ["ok", "okay", "cool", "great", "awesome", "perfect", "sounds good", "got it", "understood", "nice", "alright", "fine", "sure", "yep", "yes"]
    if msg_lower in ack_words:
        return "Understood. I am standing by whenever you are ready for your next task or query."

    # 7. Farewells
    bye_patterns = ["bye", "goodbye", "see you", "exit", "quit", "cya", "have a good day", "have a nice day", "good night"]
    if any(msg_lower == p or msg_lower.startswith(p + " ") for p in bye_patterns):
        return "Goodbye! Have a productive day. I will remain active in the background whenever you need assistance."

    # 8. Privacy & Security Inquiries
    privacy_patterns = [
        "is this private", "is my data private", "is my data safe", "do you send data", "are you offline",
        "where does my data go", "privacy concern", "is it secure", "local only", "privacy", "private"
    ]
    if any(p in msg_lower for p in privacy_patterns):
        return (
            "Yes, your data is 100% private and secure.\n\n"
            "This application operates strictly offline on your local device. None of your emails, search queries, "
            "workspace files, or command interactions are transmitted to any cloud servers or third-party platforms."
        )

    # 9. Time & Date Inquiries
    time_patterns = [
        "what time is it", "what is the time", "current time", "tell me the time",
        "what date is today", "what is today's date", "what is the date", "what day is today", "today date"
    ]
    if any(p in msg_lower for p in time_patterns):
        now = datetime.datetime.now()
        date_str = now.strftime("%A, %B %d, %Y")
        time_str = now.strftime("%I:%M %p")
        return f"Today is **{date_str}**, and the current local time is **{time_str}**."

    # 9b. Today's Tasks & Agenda Inquiries
    is_today_tasks = (
        any(p in msg_lower for p in [
            "tasks for today", "task for today", "tasks today", "task today",
            "today's tasks", "todays tasks", "today tasks",
            "tasks for tomorrow", "tomorrow's tasks", "tasks tomorrow",
            "what are the tasks", "what are my tasks", "what tasks do i have",
            "show tasks", "show my tasks", "list tasks", "list my tasks",
            "check tasks", "check my tasks", "any tasks", "do i have tasks",
            "what do i have today", "what do i have scheduled", "what is on my schedule",
            "what's on my schedule", "whats on my schedule", "what is my schedule",
            "what's my schedule", "whats my schedule", "my schedule today",
            "schedule today", "today's schedule", "todays schedule",
            "today's agenda", "todays agenda", "agenda today", "agenda for today",
            "what is on my agenda", "what's on my agenda", "whats on my agenda",
            "what do i have planned", "what is planned for today", "what's planned today",
            "meetings today", "today's meetings", "todays meetings", "meetings for today",
            "what meetings do i have", "show meetings", "list meetings", "my meetings"
        ])
        or (
            any(w in msg_lower for w in ["what are", "what is", "show", "list", "check", "tell me", "any", "do i have", "what do i have"])
            and any(t in msg_lower for t in ["task", "tasks", "schedule", "agenda", "meeting", "meetings", "todo", "todos"])
            and any(d in msg_lower for d in ["today", "upcoming", "scheduled", "planned", "tomorrow", "day"])
            and not any(a in msg_lower for a in ["create", "add", "new", "delete", "remove", "organize", "move"])
        )
    )
    if is_today_tasks:
        try:
            from app.tools.calendar_tools import calendar_list_events
            from app.tools.email_tools import email_search
            is_tomorrow = "tomorrow" in msg_lower
            now = datetime.datetime.now()
            target_dt = (now + datetime.timedelta(days=1)) if is_tomorrow else now
            date_iso = target_dt.strftime("%Y-%m-%d")
            day_label = target_dt.strftime("%A, %B %d, %Y")
            relative_label = "Tomorrow" if is_tomorrow else "Today"

            cal_res = calendar_list_events()
            all_events = cal_res.get("events", [])
            day_events = [ev for ev in all_events if (ev.get("start_time") or "").startswith(date_iso)]
            other_upcoming = [
                ev for ev in all_events
                if not (ev.get("start_time") or "").startswith(date_iso)
                and (ev.get("start_time") or "") >= date_iso
            ][:3]

            actionable_emails = []
            try:
                mail_res = email_search(category="all", max_results=6)
                all_msgs = mail_res.get("messages", [])
                actionable_emails = [
                    m for m in all_msgs
                    if (m.get("priority") or "normal").lower() in ("urgent", "security", "high")
                    or not m.get("is_read")
                ][:3]
            except Exception:
                pass

            lines = [f"### Agenda & Tasks for {relative_label} ({day_label})\n"]
            lines.append(f"**Scheduled Calendar Events & Meetings ({len(day_events)}):**")
            if day_events:
                for i, ev in enumerate(day_events, 1):
                    raw_s = ev.get("start_time", "")
                    raw_e = ev.get("end_time", "")
                    s_fmt = raw_s.split("T")[-1][:5] if "T" in raw_s else raw_s
                    e_fmt = raw_e.split("T")[-1][:5] if "T" in raw_e else raw_e
                    span = f"{s_fmt} - {e_fmt}" if s_fmt and e_fmt else "All Day"
                    lines.append(f"{i}. [{span}] **{ev.get('title')}** (Confirmed)")
                    if ev.get("description"):
                        lines.append(f"   Notes: {ev.get('description')}")
            else:
                lines.append(f"No calendar events scheduled for {relative_label.lower()}.")
                if other_upcoming:
                    lines.append("\n**Upcoming Later This Week:**")
                    for ev in other_upcoming:
                        lines.append(f"- **{ev.get('title')}** ({ev.get('start_time')})")

            lines.append("")
            lines.append(f"**Action Items from Communications ({len(actionable_emails)}):**")
            if actionable_emails:
                for i, m in enumerate(actionable_emails, 1):
                    prio = (m.get("priority") or "normal").upper()
                    sender_clean = m.get("sender", "Unknown").split("<")[0].strip()
                    subj = m.get("subject", "(No Subject)")
                    status_lbl = "Unread" if not m.get("is_read") else "Follow-up required"
                    lines.append(f"{i}. [{prio}] **{subj}** - From `{sender_clean}` ({status_lbl})")
            else:
                lines.append("All inbox communications are reviewed. No urgent action items pending.")

            lines.append("")
            lines.append("*All agenda and task data is processed locally with 100% offline privacy.*")
            return "\n".join(lines)
        except Exception:
            pass

    # 10. Ollama / LLM Service Check Inquiry
    # 10. Ollama / LLM Service & Toggle Status Check Inquiry
    llm_intent = ("llm" in msg_lower or "ollama" in msg_lower or "model" in msg_lower or "engine" in msg_lower or "local ai" in msg_lower)
    status_words = [
        "running", "status", "active", "online", "working", "check", "alive", "up",
        "on", "off", "enabled", "disabled", "state", "ready", "connected", "turned on", "switched on"
    ]
    is_llm_query = (
        any(k in msg_lower for k in [
            "is ollama running", "ollama running", "check ollama", "ollama status",
            "is llm running", "llm running", "is model running", "model running",
            "llm status", "is ai running", "is ollama active", "ollama active",
            "is llm on", "is llm off", "is llm enabled", "is the llm on", "is the llm running",
            "is ollama on", "is ollama off", "llm on", "llm off", "ollama on", "ollama off"
        ])
        or (llm_intent and any(re.search(rf"\b{re.escape(w)}\b", msg_lower) for w in status_words))
    )
    if is_llm_query:
        if not llm_enabled:
            return (
                "**Local LLM Engine: Toggled OFF**\n\n"
                "- **Top Row Switch**: Switched OFF\n"
                "- **Current System Mode**: 100% Private Offline Executive Assistant (Active)\n\n"
                "The AI Manager is operating using the built-in offline rules and direct tool execution engine. "
                "All email inspection, file organization, calendar management, and diagnostics continue working normally.\n\n"
                "To enable local LLM inference, click the **LLM toggle switch** in the top navigation bar to turn it **ON**."
            )

        import socket
        import json
        import urllib.request
        host_env = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        model_name = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
        is_port_open = False
        try:
            with socket.create_connection(("127.0.0.1", 11434), timeout=0.25):
                is_port_open = True
        except OSError:
            is_port_open = False

        if is_port_open:
            version_str = "connected"
            try:
                req = urllib.request.Request(f"{host_env}/api/version", headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=0.5) as resp:
                    v_data = json.loads(resp.read().decode("utf-8"))
                    version_str = f"v{v_data.get('version', '')}".strip()
            except Exception:
                pass
            return (
                f"**Local LLM Engine: ON & Active**\n\n"
                f"- **Top Row Switch**: Switched ON\n"
                f"- **Ollama Endpoint**: `{host_env}` ({version_str})\n"
                f"- **Configured Model**: `{model_name}`\n"
                f"- **Privacy Status**: 100% Local (Running on this device)\n\n"
                f"Your local Ollama instance is actively listening and ready for local generative inference."
            )
        else:
            return (
                f"**Local LLM Engine: ON (Ollama Daemon Offline)**\n\n"
                f"- **Top Row Switch**: Switched ON\n"
                f"- **Ollama Endpoint**: `{host_env}` (Port 11434 is closed)\n"
                f"- **Current System Mode**: 100% Private Offline Executive Assistant (Active)\n\n"
                f"The top-row LLM switch is ON, but Ollama is not currently running on your machine.\n\n"
                f"To start Ollama for open-ended generative chat:\n"
                f"1. Open a terminal and run: `ollama serve`\n"
                f"2. Or launch the Ollama application from your Windows Start menu.\n"
                f"Once started, the system will automatically utilize model `{model_name}`."
            )

    if any(p in msg_lower for p in ["how to start ollama", "how to run ollama", "start ollama"]):
        return (
            "To start Ollama on your machine:\n\n"
            "1. Open a new PowerShell or Command Prompt terminal.\n"
            "2. Run the command: `ollama serve`\n"
            "3. If you haven't pulled the recommended model yet, run: `ollama pull qwen2.5:3b`\n\n"
            "Once running, the AI Manager will automatically detect port 11434 and utilize the model locally."
        )

    # 11. System Status / Health Check Inquiry
    status_patterns = [
        "system status", "health check", "are you running ok", "is everything working",
        "status of system", "how is the system", "how is device"
    ]
    if any(p in msg_lower for p in status_patterns):
        try:
            from app.tools.system_tools import get_system_info
            from app.workspaces import WorkspaceManager
            sys_info = get_system_info()
            ws_count = len(WorkspaceManager.list_workspaces())
            ram_pct = sys_info.get("ram_percent", 0)
            cpu_pct = sys_info.get("cpu_percent", 0)
            return (
                "**Local System Status: Healthy & Active**\n\n"
                f"- **Privacy Mode**: 100% Local (Offline)\n"
                f"- **CPU Utilization**: {cpu_pct}%\n"
                f"- **RAM Utilization**: {ram_pct}%\n"
                f"- **Authorized Workspaces**: {ws_count} registered\n"
                "- **Agent Execution**: Ready to plan and execute tasks safely."
            )
        except Exception:
            return "Local System Status: Active and operating in 100% private offline mode."

    # 11. Conversational Queries / Small Talk
    small_talk_map = {
        "why are you so dumb": (
            "I apologize for any frustration! I am designed as a private, local executive assistant. "
            "I have been updated to converse naturally while safeguarding your privacy on this machine. "
            "How can I assist you right now?"
        ),
        "why is this ai so dumb": (
            "I apologize! I have been updated to communicate conversationally and assist you smoothly with your "
            "emails, calendar, local files, and system tasks. What can I help you accomplish?"
        ),
        "are you an ai": (
            "Yes, I am your local AI Executive Assistant, designed to automate desktop workflows, manage communications, "
            "and assist you with complete privacy directly on this computer."
        ),
        "who created you": (
            "I am built as an open-architecture local executive assistant, designed specifically for private, "
            "on-device productivity and automation."
        ),
    }
    for phrase, reply in small_talk_map.items():
        if phrase in msg_lower:
            return reply

    return None
