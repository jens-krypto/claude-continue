#!/usr/bin/env python3
"""
Web GUI server for Claude Continue daemon.
Runs on port 7777 and provides a control panel for monitoring sessions.
"""
import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Set
from aiohttp import web

# Import DeepSeek client for status reporting
try:
    from src.deepseek_client import deepseek_client
except ImportError:
    deepseek_client = None

# Import agent orchestrator for goal/plan management
try:
    from src.agent.orchestrator import orchestrator as agent_orchestrator
except ImportError:
    agent_orchestrator = None

logger = logging.getLogger(__name__)

# File to persist disabled session names across restarts
CONFIG_DIR = Path.home() / ".config" / "claude-continue"
DISABLED_SESSIONS_FILE = CONFIG_DIR / "disabled_sessions.json"

# Set of disabled session names (persisted to disk)
_disabled_session_names: Set[str] = set()


def _load_disabled_sessions():
    """Load disabled session names from disk."""
    global _disabled_session_names
    try:
        if DISABLED_SESSIONS_FILE.exists():
            with open(DISABLED_SESSIONS_FILE) as f:
                data = json.load(f)
                _disabled_session_names = set(data.get("disabled_names", []))
                logger.debug(f"Loaded {len(_disabled_session_names)} disabled session names")
    except Exception as e:
        logger.warning(f"Could not load disabled sessions: {e}")
        _disabled_session_names = set()


def _save_disabled_sessions():
    """Save disabled session names to disk."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(DISABLED_SESSIONS_FILE, 'w') as f:
            json.dump({"disabled_names": list(_disabled_session_names)}, f)
    except Exception as e:
        logger.warning(f"Could not save disabled sessions: {e}")


# Load on module import
_load_disabled_sessions()

# CORS middleware - only allow same-origin requests
ALLOWED_ORIGIN = 'http://localhost:7777'


@web.middleware
async def cors_middleware(request, handler):
    """CORS middleware to prevent cross-origin attacks."""
    origin = request.headers.get('Origin', '')

    # Allow requests with no Origin header (same-origin, curl, etc.)
    # But block cross-origin requests from other websites
    if origin and origin != ALLOWED_ORIGIN:
        logger.warning(f"Blocked cross-origin request from: {origin}")
        return web.json_response(
            {"error": "Cross-origin requests not allowed"},
            status=403
        )

    response = await handler(request)

    # Set CORS headers for allowed origins
    if origin == ALLOWED_ORIGIN:
        response.headers['Access-Control-Allow-Origin'] = ALLOWED_ORIGIN
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'

    return response

# Port for the web GUI
WEB_PORT = 7777

# Lock for thread-safe state modifications
_state_lock = asyncio.Lock()

# Maximum activity log entries to keep
MAX_ACTIVITY_LOG = 100

# Session state (shared with daemon)
_session_state = {
    "sessions": {},  # session_id -> {name, enabled, prompts_detected, last_action, is_claude}
    "daemon_status": "stopped",
    "auto_approve": True,
    "auto_continue": True,
    "answer_questions": False,  # Now safer with [AUTO] prefix, but still off by default
    "auto_followup": False,  # Now safer with [AUTO] prompts, but still off by default
    "paused": False,  # Whether daemon is paused
    "activity_log": [],  # List of activity events for timeline
}


def get_session_state():
    """Get current session state."""
    return _session_state


def update_session(session_id: str, name: str, enabled: bool = True, is_claude_session: bool = False, status: str = "scanning"):
    """Update or add a session.

    status can be: "scanning", "detected", "not_detected", "forced"
    """
    # Check if this session name was previously disabled
    if name in _disabled_session_names:
        enabled = False

    if session_id not in _session_state["sessions"]:
        _session_state["sessions"][session_id] = {
            "name": name,
            "enabled": enabled,
            "prompts_detected": 0,
            "last_action": None,
            "is_claude": is_claude_session,
            "status": status,
            "force_monitor": False,
        }
    else:
        _session_state["sessions"][session_id]["name"] = name
        # Only update enabled if not in disabled list (to preserve user preference)
        if name not in _disabled_session_names:
            _session_state["sessions"][session_id]["enabled"] = enabled
        _session_state["sessions"][session_id]["is_claude"] = is_claude_session
        # Don't override status if force_monitor is active
        if not _session_state["sessions"][session_id].get("force_monitor"):
            _session_state["sessions"][session_id]["status"] = status


def force_monitor_session(session_id: str, force: bool = True):
    """Force monitoring of a session regardless of Claude detection."""
    if session_id in _session_state["sessions"]:
        _session_state["sessions"][session_id]["force_monitor"] = force
        _session_state["sessions"][session_id]["status"] = "forced" if force else "not_detected"
        _session_state["sessions"][session_id]["is_claude"] = force
        return True
    return False


def is_force_monitored(session_id: str) -> bool:
    """Check if session is force monitored."""
    if session_id in _session_state["sessions"]:
        return _session_state["sessions"][session_id].get("force_monitor", False)
    return False


def remove_session(session_id: str):
    """Remove a session."""
    _session_state["sessions"].pop(session_id, None)


def increment_prompt_count(session_id: str, action: str):
    """Increment prompt count for a session."""
    if session_id in _session_state["sessions"]:
        _session_state["sessions"][session_id]["prompts_detected"] += 1
        _session_state["sessions"][session_id]["last_action"] = action


def add_activity_event(
    session_id: str,
    event_type: str,
    prompt_type: str = "",
    prompt_text: str = "",
    response: str = "",
    confidence: float = 0.0
):
    """Add an activity event to the timeline.

    Args:
        session_id: The session ID
        event_type: Type of event (approved, continued, answered, blocked, error)
        prompt_type: Type of prompt (permission, continuation, question)
        prompt_text: The prompt text (truncated)
        response: The response sent
        confidence: Pattern match confidence (0-1)
    """
    session_name = "Unknown"
    if session_id in _session_state["sessions"]:
        session_name = _session_state["sessions"][session_id].get("name", session_id[:8])

    event = {
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "session_id": session_id,
        "session_name": session_name,
        "event_type": event_type,
        "prompt_type": prompt_type,
        "prompt_text": prompt_text[:100] if prompt_text else "",  # Truncate long prompts
        "response": response[:50] if response else "",
        "confidence": confidence,
    }

    _session_state["activity_log"].insert(0, event)  # Newest first

    # Trim to max size
    if len(_session_state["activity_log"]) > MAX_ACTIVITY_LOG:
        _session_state["activity_log"] = _session_state["activity_log"][:MAX_ACTIVITY_LOG]



def is_session_enabled(session_id: str) -> bool:
    """Check if a session is enabled for automation."""
    if session_id in _session_state["sessions"]:
        return _session_state["sessions"][session_id]["enabled"]
    return True  # Default to enabled for new sessions


def set_daemon_status(status: str):
    """Set daemon status."""
    _session_state["daemon_status"] = status


# HTML template
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Claude Continue | Control Panel</title>
    <!-- Using system fonts for privacy - no external font loading -->
    <style>
        :root {
            --pink: #d94b8a;
            --pink-dark: #c73b7a;
            --gold: #e8b84a;
            --gold-light: #f4d794;
            --orange: #e8944a;
            --cyan: #4dc9e8;
            --cyan-light: #7ed9f0;
            --purple: #8b4d9e;
            --bg-pink: #d66b8a;
            --bg-gold: #daa54a;
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Roboto, monospace;
            background: linear-gradient(160deg, var(--bg-pink) 0%, var(--orange) 50%, var(--bg-gold) 100%);
            min-height: 100vh;
            color: #fff;
            overflow-x: hidden;
        }

        body::before {
            content: '';
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background:
                radial-gradient(ellipse at 20% 80%, rgba(200, 80, 120, 0.3) 0%, transparent 50%),
                radial-gradient(ellipse at 80% 20%, rgba(232, 180, 74, 0.3) 0%, transparent 50%);
            pointer-events: none;
            z-index: 0;
        }

        .container {
            max-width: 900px;
            margin: 0 auto;
            padding: 30px 20px;
            position: relative;
            z-index: 1;
        }

        .header {
            text-align: center;
            margin-bottom: 30px;
        }

        .logo-circle {
            width: 120px;
            height: 120px;
            margin: 0 auto 15px;
            border-radius: 50%;
            background: linear-gradient(180deg, rgba(255,255,255,0.1) 0%, rgba(200,80,120,0.3) 100%);
            border: 3px solid var(--pink-dark);
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 0 40px rgba(200, 80, 120, 0.3);
            font-size: 50px;
        }

        .brand-name {
            font-size: 1.8rem;
            font-weight: 800;
            letter-spacing: 6px;
            text-transform: uppercase;
            background: linear-gradient(180deg, var(--cyan-light) 0%, var(--cyan) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .brand-sub {
            font-size: 1rem;
            font-weight: 600;
            letter-spacing: 8px;
            text-transform: uppercase;
            color: #fff;
            text-shadow: 0 0 20px rgba(232, 180, 74, 0.8);
        }

        .status-card {
            background: rgba(0,0,0,0.2);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 25px;
            margin-bottom: 25px;
            border: 2px solid rgba(255,255,255,0.1);
        }

        .status-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }

        .status-title {
            font-size: 1rem;
            font-weight: 600;
            letter-spacing: 3px;
            text-transform: uppercase;
            color: var(--gold);
        }

        .status-badge {
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 0.7rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 2px;
        }

        .status-badge.running {
            background: linear-gradient(135deg, #22c55e, #16a34a);
            color: #fff;
        }

        .status-badge.stopped {
            background: linear-gradient(135deg, #ef4444, #dc2626);
            color: #fff;
        }

        .toggle-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }

        .toggle-row:last-child {
            border-bottom: none;
        }

        .toggle-label {
            font-size: 0.85rem;
            letter-spacing: 1px;
        }

        .toggle-switch {
            position: relative;
            width: 50px;
            height: 26px;
        }

        .toggle-switch input {
            opacity: 0;
            width: 0;
            height: 0;
        }

        .toggle-slider {
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(255,255,255,0.2);
            border-radius: 26px;
            transition: 0.3s;
        }

        .toggle-slider:before {
            position: absolute;
            content: "";
            height: 20px;
            width: 20px;
            left: 3px;
            bottom: 3px;
            background: #fff;
            border-radius: 50%;
            transition: 0.3s;
        }

        input:checked + .toggle-slider {
            background: var(--cyan);
        }

        input:checked + .toggle-slider:before {
            transform: translateX(24px);
        }

        .sessions-section {
            background: rgba(0,0,0,0.2);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 25px;
            margin-bottom: 25px;
            border: 2px solid rgba(255,255,255,0.1);
        }

        .section-title {
            font-size: 1rem;
            font-weight: 600;
            letter-spacing: 3px;
            text-transform: uppercase;
            color: var(--gold);
            margin-bottom: 20px;
        }

        .session-card {
            background: rgba(0,0,0,0.3);
            border-radius: 12px;
            padding: 15px 20px;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 15px;
            border-left: 4px solid var(--cyan);
        }

        .session-card.disabled {
            border-left-color: rgba(255,255,255,0.3);
            opacity: 0.6;
        }

        .session-card.claude-session {
            border-left-color: var(--gold);
            background: rgba(232, 184, 74, 0.1);
        }

        .session-card.other-session {
            border-left-color: rgba(255,255,255,0.2);
            opacity: 0.5;
        }

        .claude-badge {
            display: inline-block;
            background: var(--gold);
            color: #000;
            font-size: 0.55rem;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 4px;
            margin-left: 8px;
            letter-spacing: 1px;
            vertical-align: middle;
        }

        /* Status badges */
        .status-badge-session {
            display: inline-block;
            font-size: 0.5rem;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 4px;
            margin-left: 8px;
            letter-spacing: 1px;
            vertical-align: middle;
        }

        .status-badge-session.scanning {
            background: var(--cyan);
            color: #000;
            animation: pulse-scan 1.5s infinite;
        }

        .status-badge-session.detected {
            background: var(--gold);
            color: #000;
        }

        .status-badge-session.not-detected {
            background: rgba(255,255,255,0.2);
            color: rgba(255,255,255,0.7);
        }

        .status-badge-session.forced {
            background: #e066ff;
            color: #000;
        }

        @keyframes pulse-scan {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        /* Force monitor button */
        .force-btn {
            background: rgba(224, 102, 255, 0.2);
            border: 1px solid rgba(224, 102, 255, 0.5);
            color: #e066ff;
            font-size: 0.6rem;
            padding: 4px 10px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 600;
            letter-spacing: 1px;
            transition: all 0.2s;
        }

        .force-btn:hover {
            background: rgba(224, 102, 255, 0.3);
            border-color: #e066ff;
        }

        .force-btn.active {
            background: #e066ff;
            color: #000;
        }

        .session-icon {
            font-size: 1.5rem;
        }

        .session-info {
            flex: 1;
        }

        .session-name {
            font-size: 0.9rem;
            font-weight: 600;
            margin-bottom: 4px;
        }

        .session-stats {
            font-size: 0.7rem;
            opacity: 0.7;
            letter-spacing: 1px;
        }

        .no-sessions {
            text-align: center;
            padding: 40px 20px;
            opacity: 0.6;
            font-size: 0.85rem;
            letter-spacing: 2px;
        }

        /* Activity Timeline */
        .activity-section {
            background: rgba(0,0,0,0.2);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 25px;
            margin-bottom: 25px;
            border: 2px solid rgba(255,255,255,0.1);
        }

        .activity-timeline {
            max-height: 400px;
            overflow-y: auto;
        }

        .activity-event {
            background: rgba(0,0,0,0.3);
            border-radius: 10px;
            padding: 12px 15px;
            margin-bottom: 10px;
            border-left: 3px solid var(--cyan);
            position: relative;
        }

        .activity-event.approved {
            border-left-color: #28a745;
        }

        .activity-event.continue {
            border-left-color: var(--cyan);
        }

        .activity-event.answered {
            border-left-color: var(--gold);
        }

        .activity-event.followup {
            border-left-color: #e066ff;
        }

        .activity-event.regex {
            border-left-color: #fd7e14;
        }

        .activity-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 6px;
        }

        .activity-type {
            font-weight: 600;
            font-size: 0.8rem;
            letter-spacing: 1px;
        }

        .activity-time {
            font-size: 0.7rem;
            opacity: 0.6;
            font-family: monospace;
        }

        .activity-text {
            font-size: 0.75rem;
            opacity: 0.8;
            margin-bottom: 4px;
            line-height: 1.4;
            word-break: break-word;
        }

        .activity-meta {
            font-size: 0.65rem;
            opacity: 0.5;
            display: flex;
            gap: 12px;
        }

        .no-activity {
            text-align: center;
            padding: 40px 20px;
            opacity: 0.6;
            font-size: 0.85rem;
            letter-spacing: 2px;
        }

        .footer {
            text-align: center;
            margin-top: 40px;
            padding: 20px;
        }

        .footer-links {
            display: flex;
            justify-content: center;
            gap: 20px;
            margin-bottom: 15px;
            flex-wrap: wrap;
        }

        .footer-link {
            color: #fff;
            text-decoration: none;
            font-size: 0.7rem;
            font-weight: 600;
            letter-spacing: 2px;
            text-transform: uppercase;
            padding: 10px 18px;
            border-radius: 25px;
            background: rgba(0,0,0,0.2);
            transition: all 0.3s ease;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }

        .footer-link:hover {
            background: rgba(0,0,0,0.4);
            transform: translateY(-2px);
        }

        .footer-link.telegram {
            background: linear-gradient(135deg, #0088cc, #00aced);
        }

        .footer-link.website {
            background: linear-gradient(135deg, var(--pink-dark), var(--purple));
        }

        .footer-copyright {
            font-size: 0.6rem;
            letter-spacing: 2px;
            text-transform: uppercase;
            opacity: 0.5;
        }

        /* Info Section */
        .info-section {
            background: rgba(0,0,0,0.2);
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
        }

        .info-text {
            font-size: 0.9rem;
            opacity: 0.9;
            margin-bottom: 15px;
        }

        .feature-list {
            list-style: none;
            padding: 0;
            margin: 0 0 15px 0;
        }

        .feature-list li {
            font-size: 0.85rem;
            padding: 5px 0;
            opacity: 0.85;
        }

        .info-note {
            font-size: 0.8rem;
            color: var(--gold);
            padding: 10px;
            background: rgba(232,184,74,0.1);
            border-radius: 8px;
            margin-bottom: 15px;
        }

        .setup-guide {
            background: rgba(0,0,0,0.2);
            border-radius: 10px;
            padding: 12px;
        }

        .setup-guide summary {
            cursor: pointer;
            font-weight: 600;
            font-size: 0.9rem;
        }

        .setup-steps {
            margin: 15px 0 0 20px;
            padding: 0;
        }

        .setup-steps li {
            font-size: 0.85rem;
            padding: 6px 0;
            opacity: 0.85;
        }

        kbd {
            background: rgba(255,255,255,0.15);
            padding: 2px 6px;
            border-radius: 4px;
            font-family: monospace;
            font-size: 0.8rem;
        }

        .disclaimer {
            font-size: 0.75rem;
            color: #fff;
            padding: 12px;
            background: rgba(180, 40, 40, 0.9);
            border: 1px solid rgba(220, 53, 69, 0.8);
            border-radius: 8px;
            margin-top: 15px;
            text-align: center;
            text-shadow: 0 1px 1px rgba(0,0,0,0.3);
        }

        .risk-badge {
            font-size: 0.55rem;
            padding: 2px 6px;
            border-radius: 4px;
            margin-left: 8px;
            font-weight: 700;
            letter-spacing: 0.5px;
        }

        .risk-badge.high {
            background: #dc3545;
            color: #fff;
            text-shadow: 0 1px 1px rgba(0,0,0,0.3);
        }

        .risk-badge.medium {
            background: #ffc107;
            color: #000;
        }

        .risk-badge.medium-high {
            background: #fd7e14;
            color: #fff;
            text-shadow: 0 1px 1px rgba(0,0,0,0.3);
        }

        /* Custom CSS Tooltips */
        .toggle-row {
            position: relative;
        }

        .toggle-row[data-tooltip] {
            cursor: help;
        }

        .toggle-row[data-tooltip]::before {
            content: '';
            position: absolute;
            bottom: calc(100% + 5px);
            left: 50%;
            transform: translateX(-50%);
            border: 8px solid transparent;
            border-top-color: rgba(0, 0, 0, 0.95);
            opacity: 0;
            visibility: hidden;
            transition: opacity 0.2s;
            z-index: 101;
            pointer-events: none;
        }

        .toggle-row[data-tooltip]::after {
            content: attr(data-tooltip);
            position: absolute;
            bottom: calc(100% + 20px);
            left: 50%;
            transform: translateX(-50%);
            background: rgba(0, 0, 0, 0.95);
            color: #fff;
            padding: 12px 16px;
            border-radius: 8px;
            font-size: 0.8rem;
            font-weight: 400;
            width: 300px;
            max-width: 90vw;
            text-align: left;
            line-height: 1.5;
            opacity: 0;
            visibility: hidden;
            transition: opacity 0.2s;
            z-index: 100;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
            pointer-events: none;
        }

        .toggle-row[data-tooltip]:hover::before,
        .toggle-row[data-tooltip]:hover::after {
            opacity: 1;
            visibility: visible;
        }

        /* Control Section */
        .control-section {
            background: rgba(0,0,0,0.2);
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
            text-align: center;
        }

        .control-buttons {
            display: flex;
            justify-content: center;
            gap: 15px;
            margin-bottom: 15px;
        }

        .control-btn {
            padding: 12px 24px;
            border: none;
            border-radius: 25px;
            font-size: 0.9rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .control-btn.pause {
            background: linear-gradient(135deg, var(--gold), var(--orange));
            color: #000;
        }

        .control-btn.resume {
            background: linear-gradient(135deg, #2ecc71, #27ae60);
            color: #fff;
        }

        .control-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0,0,0,0.3);
        }

        .control-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }

        .control-hint {
            font-size: 0.75rem;
            opacity: 0.6;
        }

        /* Disconnected Overlay */
        .disconnected-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.9);
            display: none;
            justify-content: center;
            align-items: center;
            z-index: 1000;
            flex-direction: column;
        }

        .disconnected-overlay.visible {
            display: flex;
        }

        .disconnected-icon {
            font-size: 4rem;
            margin-bottom: 20px;
        }

        .disconnected-title {
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Roboto, monospace;
            font-size: 1.5rem;
            color: var(--gold);
            margin-bottom: 10px;
        }

        .disconnected-text {
            font-size: 0.9rem;
            opacity: 0.7;
            text-align: center;
            max-width: 300px;
        }

        @media (max-width: 600px) {
            .brand-name { font-size: 1.4rem; letter-spacing: 4px; }
            .brand-sub { font-size: 0.8rem; letter-spacing: 6px; }
            .footer-links { flex-direction: column; gap: 10px; }
            .control-buttons { flex-direction: column; }
        }
    </style>
</head>
<body>
    <!-- Disconnected Overlay -->
    <div class="disconnected-overlay" id="disconnectedOverlay">
        <div class="disconnected-icon">🔌</div>
        <div class="disconnected-title">DISCONNECTED</div>
        <div class="disconnected-text">
            The daemon has stopped. Press Ctrl+C was detected or the process ended.
            Restart with ./claudeContinue.sh
        </div>
    </div>

    <div class="container">
        <header class="header">
            <div class="logo-circle">
                <!-- Using emoji instead of external image for privacy -->
                <span style="font-size: 60px; filter: drop-shadow(0 0 10px var(--cyan));">🤖</span>
            </div>
            <h1 class="brand-name">CLAUDE</h1>
            <p class="brand-sub">CONTINUE</p>
        </header>

        <div class="status-card">
            <div class="status-header">
                <span class="status-title">Daemon Status</span>
                <span class="status-badge" id="daemonStatus">Loading...</span>
            </div>
            <div class="toggle-row" data-tooltip="HIGH RISK: Claude will automatically approve all permission requests. Files may be modified or deleted without your review.">
                <span class="toggle-label">Auto-Approve Permissions <span class="risk-badge high">HIGH RISK</span></span>
                <label class="toggle-switch">
                    <input type="checkbox" id="autoApprove" onchange="updateSetting('auto_approve', this.checked)">
                    <span class="toggle-slider"></span>
                </label>
            </div>
            <div class="toggle-row" data-tooltip="MEDIUM RISK: Claude will continue working without pausing. Long operations complete without checkpoints.">
                <span class="toggle-label">Auto-Continue <span class="risk-badge medium">MEDIUM</span></span>
                <label class="toggle-switch">
                    <input type="checkbox" id="autoContinue" onchange="updateSetting('auto_continue', this.checked)">
                    <span class="toggle-slider"></span>
                </label>
            </div>
            <div class="toggle-row" data-tooltip="HIGH RISK: Uses pattern matching, not understanding. May give wrong answers to important decisions.">
                <span class="toggle-label">Answer Questions <span class="risk-badge high">HIGH RISK</span></span>
                <label class="toggle-switch">
                    <input type="checkbox" id="answerQuestions" onchange="updateSetting('answer_questions', this.checked)">
                    <span class="toggle-slider"></span>
                </label>
            </div>
            <div class="toggle-row" data-tooltip="MEDIUM-HIGH RISK: Sends prompts when Claude is idle. May trigger actions while you're away.">
                <span class="toggle-label">Auto Follow-up <span class="risk-badge medium-high">MEDIUM-HIGH</span></span>
                <label class="toggle-switch">
                    <input type="checkbox" id="autoFollowup" onchange="updateSetting('auto_followup', this.checked)">
                    <span class="toggle-slider"></span>
                </label>
            </div>
        </div>

        <div class="info-section">
            <h3 class="section-title">What is Claude Continue?</h3>
            <p class="info-text">
                Claude Continue automatically handles Claude Code prompts in iTerm2:
            </p>
            <ul class="feature-list">
                <li>✅ Auto-approves permission requests (press 1)</li>
                <li>✅ Sends "continue" when Claude pauses</li>
                <li>✅ Answers common questions intelligently</li>
                <li>✅ Sends follow-up prompts when Claude is idle</li>
            </ul>
            <p class="info-note">⚠️ Requires iTerm2 on macOS with Python API enabled</p>

            <details class="setup-guide">
                <summary>📋 iTerm2 Setup Guide</summary>
                <ol class="setup-steps">
                    <li>Open iTerm2 Preferences (<kbd>Cmd</kbd>+<kbd>,</kbd>)</li>
                    <li>Go to <strong>General</strong> → <strong>Magic</strong></li>
                    <li>Enable <strong>"Enable Python API"</strong></li>
                    <li>Restart iTerm2</li>
                </ol>
            </details>

            <div class="disclaimer">
                ⚠️ <strong>DISCLAIMER:</strong> This software is provided as-is. You run this service at your own risk.
                Auto-approving commands can be dangerous. Review the settings carefully.
            </div>
        </div>

        <div class="control-section">
            <h3 class="section-title">Daemon Controls</h3>
            <div class="control-buttons">
                <button class="control-btn pause" id="pauseBtn" onclick="controlDaemon('pause')">
                    ⏸ Pause
                </button>
                <button class="control-btn resume" id="resumeBtn" onclick="controlDaemon('resume')">
                    ▶ Resume
                </button>
            </div>
            <p class="control-hint">Press <kbd>Ctrl</kbd>+<kbd>C</kbd> in terminal to stop daemon</p>
        </div>

        <div class="sessions-section">
            <h3 class="section-title">Active Claude Sessions</h3>
            <div id="sessionsList">
                <div class="no-sessions">No active sessions detected</div>
            </div>
        </div>

        <div class="activity-section">
            <h3 class="section-title">📜 Activity Timeline</h3>
            <div id="activityTimeline" class="activity-timeline">
                <div class="no-activity">No activity yet</div>
            </div>
        </div>

        <footer class="footer">
            <div class="footer-links">
                <a href="https://addicted.bot" target="_blank" class="footer-link website">
                    🌐 ADDICTED.BOT
                </a>
                <a href="https://t.me/AnomalyAlpha" target="_blank" class="footer-link telegram">
                    ✈️ TELEGRAM
                </a>
                <a href="https://x.com/AddictedAnomaly" target="_blank" class="footer-link">
                    𝕏 TWITTER
                </a>
            </div>
            <p class="footer-copyright">
                Claude Continue | Anomaly Alpha Labs
            </p>
        </footer>
    </div>

    <script>
        let connectionLost = false;

        function showDisconnected() {
            document.getElementById('disconnectedOverlay').classList.add('visible');
        }

        function hideDisconnected() {
            document.getElementById('disconnectedOverlay').classList.remove('visible');
        }

        async function fetchStatus() {
            try {
                const response = await fetch('/api/status');
                const data = await response.json();
                if (connectionLost) {
                    hideDisconnected();
                    connectionLost = false;
                }
                updateUI(data);
            } catch (error) {
                console.error('Failed to fetch status:', error);
                if (!connectionLost) {
                    showDisconnected();
                    connectionLost = true;
                }
            }
        }

        function updateUI(data) {
            // Update daemon status
            const statusBadge = document.getElementById('daemonStatus');
            statusBadge.textContent = data.daemon_status.toUpperCase();
            statusBadge.className = 'status-badge ' + (data.daemon_status === 'running' ? 'running' : 'stopped');

            // Update toggles
            document.getElementById('autoApprove').checked = data.auto_approve;
            document.getElementById('autoContinue').checked = data.auto_continue;
            document.getElementById('answerQuestions').checked = data.answer_questions;
            document.getElementById('autoFollowup').checked = data.auto_followup;

            // Update sessions list
            const sessionsList = document.getElementById('sessionsList');
            const sessions = Object.entries(data.sessions);

            if (sessions.length === 0) {
                sessionsList.innerHTML = '<div class="no-sessions">No active sessions detected</div>';
            } else {
                // Sort: Claude sessions first, then by name
                sessions.sort((a, b) => {
                    if (a[1].is_claude && !b[1].is_claude) return -1;
                    if (!a[1].is_claude && b[1].is_claude) return 1;
                    return a[1].name.localeCompare(b[1].name);
                });

                sessionsList.innerHTML = sessions.map(([id, session]) => `
                    <div class="session-card ${session.enabled ? '' : 'disabled'} ${session.is_claude ? 'claude-session' : 'other-session'}">
                        <span class="session-icon">${getSessionIcon(session)}</span>
                        <div class="session-info">
                            <div class="session-name">
                                ${escapeHtml(session.name)}
                                ${getStatusBadge(session)}
                            </div>
                            <div class="session-stats">
                                ${getSessionStats(session)}
                            </div>
                        </div>
                        ${session.is_claude ? `
                        <label class="toggle-switch">
                            <input type="checkbox" ${session.enabled ? 'checked' : ''}
                                   onchange="toggleSession('${id}', this.checked)">
                            <span class="toggle-slider"></span>
                        </label>
                        ` : `
                        <button class="force-btn ${session.force_monitor ? 'active' : ''}"
                                onclick="forceMonitor('${id}', ${!session.force_monitor})">
                            ${session.force_monitor ? 'UNFORCE' : 'FORCE MONITOR'}
                        </button>
                        `}
                    </div>
                `).join('');
            }
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function getSessionIcon(session) {
            const status = session.status || 'scanning';
            if (status === 'scanning') return '🔍';
            if (status === 'forced') return '⚡';
            if (session.is_claude) return '🤖';
            return '💻';
        }

        function getStatusBadge(session) {
            const status = session.status || 'scanning';
            const statusLabels = {
                'scanning': 'SCANNING...',
                'detected': 'CLAUDE CODE',
                'not_detected': 'NOT DETECTED',
                'forced': 'FORCE MONITORED'
            };
            const cssClass = status.replace('_', '-');
            return `<span class="status-badge-session ${cssClass}">${statusLabels[status] || status.toUpperCase()}</span>`;
        }

        function getSessionStats(session) {
            const status = session.status || 'scanning';
            if (status === 'scanning') {
                return 'Analyzing terminal content...';
            }
            if (session.is_claude) {
                const prompts = session.prompts_detected || 0;
                const lastAction = session.last_action ? ` • Last: ${escapeHtml(session.last_action)}` : '';
                return `${prompts} prompts handled${lastAction}`;
            }
            return 'Not Claude Code - click Force Monitor to override';
        }

        async function forceMonitor(sessionId, force) {
            try {
                await fetch('/api/sessions/' + sessionId + '/force', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ force: force })
                });
                fetchStatus();
            } catch (error) {
                console.error('Failed to force monitor session:', error);
            }
        }

        async function updateSetting(setting, value) {
            try {
                await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ [setting]: value })
                });
            } catch (error) {
                console.error('Failed to update setting:', error);
            }
        }

        async function toggleSession(sessionId, enabled) {
            try {
                await fetch('/api/sessions/' + sessionId, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled: enabled })
                });
            } catch (error) {
                console.error('Failed to toggle session:', error);
            }
        }

        async function controlDaemon(action) {
            try {
                const response = await fetch('/api/control/' + action, {
                    method: 'POST'
                });
                const data = await response.json();
                if (data.success) {
                    fetchStatus();
                }
            } catch (error) {
                console.error('Failed to control daemon:', error);
            }
        }

        function updateControlButtons(isPaused) {
            const pauseBtn = document.getElementById('pauseBtn');
            const resumeBtn = document.getElementById('resumeBtn');
            pauseBtn.disabled = isPaused;
            resumeBtn.disabled = !isPaused;
        }

        // Extended updateUI to handle pause state
        const originalUpdateUI = updateUI;
        updateUI = function(data) {
            originalUpdateUI(data);
            updateControlButtons(data.paused || false);
        };

        // Activity Timeline
        async function fetchActivity() {
            try {
                const response = await fetch('/api/activity?limit=30');
                const events = await response.json();
                updateActivityTimeline(events);
            } catch (error) {
                console.error('Failed to fetch activity:', error);
            }
        }

        function updateActivityTimeline(events) {
            const timeline = document.getElementById('activityTimeline');
            timeline.replaceChildren();

            if (!events || events.length === 0) {
                const noActivity = document.createElement('div');
                noActivity.className = 'no-activity';
                noActivity.textContent = 'No activity yet';
                timeline.appendChild(noActivity);
                return;
            }

            events.forEach(event => {
                const eventDiv = document.createElement('div');
                eventDiv.className = 'activity-event ' + event.event_type;

                const header = document.createElement('div');
                header.className = 'activity-header';

                const typeSpan = document.createElement('span');
                typeSpan.className = 'activity-type';
                typeSpan.textContent = getEventIcon(event.event_type) + ' ' + getEventLabel(event.event_type);
                header.appendChild(typeSpan);

                const timeSpan = document.createElement('span');
                timeSpan.className = 'activity-time';
                timeSpan.textContent = event.timestamp;
                header.appendChild(timeSpan);

                eventDiv.appendChild(header);

                if (event.prompt_text) {
                    const textDiv = document.createElement('div');
                    textDiv.className = 'activity-text';
                    textDiv.textContent = '"' + event.prompt_text + '"';
                    eventDiv.appendChild(textDiv);
                }

                const metaDiv = document.createElement('div');
                metaDiv.className = 'activity-meta';

                const sessionSpan = document.createElement('span');
                sessionSpan.textContent = '📍 ' + event.session_name;
                metaDiv.appendChild(sessionSpan);

                if (event.response) {
                    const responseSpan = document.createElement('span');
                    responseSpan.textContent = '↪ ' + event.response;
                    metaDiv.appendChild(responseSpan);
                }

                if (event.confidence) {
                    const confSpan = document.createElement('span');
                    confSpan.textContent = '🎯 ' + (event.confidence * 100).toFixed(0) + '%';
                    metaDiv.appendChild(confSpan);
                }

                eventDiv.appendChild(metaDiv);
                timeline.appendChild(eventDiv);
            });
        }

        function getEventIcon(eventType) {
            const icons = {
                'approved': '✅',
                'continue': '▶️',
                'answered': '💬',
                'followup': '📤',
                'regex': '🔧',
                'blocked': '🚫'
            };
            return icons[eventType] || '📌';
        }

        function getEventLabel(eventType) {
            const labels = {
                'approved': 'Approved permission',
                'continue': 'Sent continue',
                'answered': 'Answered question',
                'followup': 'Sent follow-up',
                'regex': 'Regex response',
                'blocked': 'Blocked'
            };
            return labels[eventType] || eventType;
        }

        // Initial fetch
        fetchStatus();
        fetchActivity();

        // Poll every 2 seconds
        setInterval(fetchStatus, 2000);
        setInterval(fetchActivity, 2000);
    </script>
</body>
</html>
"""


async def handle_index(request):
    """Serve the main HTML page."""
    return web.Response(text=HTML_TEMPLATE, content_type='text/html')


async def handle_status(request):
    """Get current status including DeepSeek info."""
    response = dict(_session_state)
    # Add DeepSeek status
    if deepseek_client:
        response["deepseek"] = deepseek_client.get_status()
    else:
        response["deepseek"] = {"enabled": False, "reason": "Not loaded"}
    return web.json_response(response)


async def handle_settings(request):
    """Update settings."""
    try:
        data = await request.json()
        async with _state_lock:
            for key in ['auto_approve', 'auto_continue', 'answer_questions', 'auto_followup']:
                if key in data:
                    _session_state[key] = bool(data[key])
        return web.json_response({"success": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def handle_session_toggle(request):
    """Toggle session enabled state."""
    try:
        session_id = request.match_info['session_id']
        # Validate session_id format (alphanumeric with hyphens/underscores)
        if not re.match(r'^[A-Za-z0-9_-]+$', session_id):
            return web.json_response({"error": "Invalid session ID format"}, status=400)

        data = await request.json()
        enabled = bool(data.get("enabled", True))

        async with _state_lock:
            if session_id in _session_state["sessions"]:
                session_name = _session_state["sessions"][session_id].get("name", "")
                _session_state["sessions"][session_id]["enabled"] = enabled

                # Persist the user's preference by session name
                if session_name:
                    if enabled:
                        # Remove from disabled list
                        _disabled_session_names.discard(session_name)
                    else:
                        # Add to disabled list
                        _disabled_session_names.add(session_name)
                    _save_disabled_sessions()
                    logger.debug(f"Session '{session_name}' {'enabled' if enabled else 'disabled'} (persisted)")

        return web.json_response({"success": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def handle_control(request):
    """Handle daemon control actions (pause/resume)."""
    try:
        action = request.match_info['action']
        # Validate action is one of the allowed values
        if action not in ('pause', 'resume'):
            return web.json_response({"error": f"Unknown action: {action}"}, status=400)

        async with _state_lock:
            if action == 'pause':
                _session_state["paused"] = True
                _session_state["daemon_status"] = "paused"
                logger.info("Daemon paused by user")
                return web.json_response({"success": True, "status": "paused"})
            elif action == 'resume':
                _session_state["paused"] = False
                _session_state["daemon_status"] = "running"
                logger.info("Daemon resumed by user")
                return web.json_response({"success": True, "status": "running"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def handle_force_monitor(request):
    """Force monitor a session regardless of Claude detection."""
    try:
        session_id = request.match_info['session_id']
        # Validate session_id format (alphanumeric with hyphens/underscores)
        if not re.match(r'^[A-Za-z0-9_-]+$', session_id):
            return web.json_response({"error": "Invalid session ID format"}, status=400)

        data = await request.json()
        force = bool(data.get("force", True))

        async with _state_lock:
            if force_monitor_session(session_id, force):
                logger.info(f"Force monitor {'enabled' if force else 'disabled'} for session {session_id}")
                return web.json_response({"success": True, "force": force})
        return web.json_response({"error": "Session not found"}, status=404)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def handle_activity(request):
    """Get activity timeline events."""
    limit = int(request.query.get('limit', 50))
    limit = min(max(limit, 1), MAX_ACTIVITY_LOG)  # Clamp between 1 and max
    return web.json_response(_session_state["activity_log"][:limit])


# ============================================================
# Agent/Goal API Endpoints
# ============================================================

async def handle_agent_status(request):
    """Get agent status for a session (goal, plan, state)."""
    try:
        session_id = request.match_info['session_id']
        if not re.match(r'^[A-Za-z0-9_-]+$', session_id):
            return web.json_response({"error": "Invalid session ID format"}, status=400)

        if not agent_orchestrator:
            return web.json_response({"error": "Agent module not available"}, status=503)

        status = agent_orchestrator.get_session_status(session_id)
        # Add learning status
        status["learning"] = agent_orchestrator.learning.get_status()

        return web.json_response(status)
    except Exception as e:
        logger.error(f"Agent status error: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def handle_set_goal(request):
    """Set a goal for a session."""
    try:
        session_id = request.match_info['session_id']
        if not re.match(r'^[A-Za-z0-9_-]+$', session_id):
            return web.json_response({"error": "Invalid session ID format"}, status=400)

        if not agent_orchestrator:
            return web.json_response({"error": "Agent module not available"}, status=503)

        data = await request.json()
        description = data.get("description", "").strip()
        if not description:
            return web.json_response({"error": "Goal description required"}, status=400)

        success_criteria = data.get("success_criteria", [])
        priority = int(data.get("priority", 1))

        goal = agent_orchestrator.set_goal(
            session_id=session_id,
            description=description,
            success_criteria=success_criteria,
            priority=priority,
        )

        # Optionally create a plan if steps provided
        steps = data.get("plan_steps", [])
        plan = None
        if steps:
            plan = agent_orchestrator.create_plan(
                goal_id=goal.goal_id,
                session_id=session_id,
                steps=steps,
            )

        return web.json_response({
            "success": True,
            "goal": goal.to_dict(),
            "plan": plan.to_dict() if plan else None,
        })
    except Exception as e:
        logger.error(f"Set goal error: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def handle_delete_goal(request):
    """Clear/complete the active goal for a session."""
    try:
        session_id = request.match_info['session_id']
        if not re.match(r'^[A-Za-z0-9_-]+$', session_id):
            return web.json_response({"error": "Invalid session ID format"}, status=400)

        if not agent_orchestrator:
            return web.json_response({"error": "Agent module not available"}, status=503)

        active_goal = agent_orchestrator.goals.get_active_goal(session_id)
        if not active_goal:
            return web.json_response({"error": "No active goal"}, status=404)

        # Complete or fail the goal based on request
        data = await request.json() if request.can_read_body else {}
        reason = data.get("reason", "Manually cleared")
        success = data.get("success", False)

        if success:
            agent_orchestrator.goals.complete_goal(active_goal.goal_id, reason)
        else:
            agent_orchestrator.goals.fail_goal(active_goal.goal_id, reason)

        return web.json_response({"success": True, "goal_id": active_goal.goal_id})
    except Exception as e:
        logger.error(f"Delete goal error: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def handle_replan(request):
    """Trigger replanning for a session."""
    try:
        session_id = request.match_info['session_id']
        if not re.match(r'^[A-Za-z0-9_-]+$', session_id):
            return web.json_response({"error": "Invalid session ID format"}, status=400)

        if not agent_orchestrator:
            return web.json_response({"error": "Agent module not available"}, status=503)

        active_goal = agent_orchestrator.goals.get_active_goal(session_id)
        if not active_goal:
            return web.json_response({"error": "No active goal"}, status=404)

        data = await request.json()
        reason = data.get("reason", "User requested replan")
        new_steps = data.get("steps", [])

        if not new_steps:
            return web.json_response({"error": "New plan steps required"}, status=400)

        plan = agent_orchestrator.plans.replan(
            goal_id=active_goal.goal_id,
            session_id=session_id,
            reason=reason,
            new_steps=new_steps,
        )

        return web.json_response({
            "success": True,
            "plan": plan.to_dict(),
        })
    except Exception as e:
        logger.error(f"Replan error: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def handle_full_agent_status(request):
    """Get full agent system status (all sessions)."""
    try:
        if not agent_orchestrator:
            return web.json_response({"error": "Agent module not available"}, status=503)

        return web.json_response(agent_orchestrator.get_full_status())
    except Exception as e:
        logger.error(f"Full agent status error: {e}")
        return web.json_response({"error": str(e)}, status=500)


def is_paused() -> bool:
    """Check if daemon is paused."""
    return _session_state.get("paused", False)


def create_app():
    """Create the web application."""
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get('/', handle_index)
    app.router.add_get('/api/status', handle_status)
    app.router.add_get('/api/activity', handle_activity)
    app.router.add_post('/api/settings', handle_settings)
    app.router.add_post('/api/sessions/{session_id}', handle_session_toggle)
    app.router.add_post('/api/sessions/{session_id}/force', handle_force_monitor)
    app.router.add_post('/api/control/{action}', handle_control)

    # Agent/Goal endpoints
    app.router.add_get('/api/agent/status', handle_full_agent_status)
    app.router.add_get('/api/sessions/{session_id}/agent', handle_agent_status)
    app.router.add_post('/api/sessions/{session_id}/goal', handle_set_goal)
    app.router.add_delete('/api/sessions/{session_id}/goal', handle_delete_goal)
    app.router.add_post('/api/sessions/{session_id}/replan', handle_replan)

    return app


async def start_web_server():
    """Start the web server."""
    app = create_app()
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', WEB_PORT)
    await site.start()
    logger.info(f"Web GUI running at http://localhost:{WEB_PORT}")
    set_daemon_status("running")
    return runner


async def stop_web_server(runner):
    """Stop the web server."""
    await runner.cleanup()


if __name__ == "__main__":
    # Test the web server standalone
    logging.basicConfig(level=logging.INFO)

    async def main():
        runner = await start_web_server()
        print(f"Web GUI running at http://localhost:{WEB_PORT}")
        print("Press Ctrl+C to stop")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            await stop_web_server(runner)

    asyncio.run(main())
