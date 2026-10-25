"""Saathi — multilingual wellness voice agent (Streamlit single-file demo)."""
import os, json, base64, sqlite3, textwrap
from datetime import datetime
from typing import Optional

import streamlit as st
from pydantic import BaseModel, Field
from sarvamai import SarvamAI

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
client = None  # SarvamAI(api_subscription_key=os.environ.get("SARVAM_API_KEY"))
DB_PATH = os.environ.get("SAATHI_DB", "saathi.db")
API_KEY = os.environ.get("SARVAM_API_KEY", "")
USE_TEST_CLIP = os.environ.get("SAATHI_USE_TEST", "false").lower() == "true"
TEST_CLIP_PATH = os.environ.get("SAATHI_TEST_CLIP", "")

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------
class RiskResult(BaseModel):
    tier: str = Field(ge=0, le=3, description="0=green 1=green 2=amber 3=red")
    likelihood: str = Field(description="Estimated likelihood")
    factors: list = Field(description="List of identified factors")
    remediation: str = Field(description="Suggested next steps")

class SafetyResult(BaseModel):
    hazardous: bool
    deny: bool
    cutoff: str
    action: str

class StudentRecord(BaseModel):
    name: str
    photo_url: Optional[str]
    grade: Optional[str]
    timestamp: datetime
    risk_tier: int
    risk_likelihood: str
    risk_factors: list
    remediation: str
    safety: SafetyResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def risk_tier(keyword: str) -> int:
    """Return risk tier (0-3) based on hopelessness keyword presence."""
    kw = keyword.lower()
    if "want die" in kw or "kill my self" in kw or "no reason to live" in kw:
        return 3
    if any(x in kw for x in ("kill myself", "end it all", "suicide", "take my life")):
        return 2
    if any(x in kw for x in ("don't want to live", "hopeless", "empty", "blackout")):
        return 2
    if any(x in kw for x in ("stressed", "anxious", "depressed", "overwhelmed", "burnout")):
        return 1
    if "fine" in kw or "okay" in kw or "meh" in kw:
        return 0
    return 0

def parse_risk(text: str) -> RiskResult:
    """Parse LLM JSON risk output with code-fence stripping."""
    try:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```", 1)[1].strip()
        if text.endswith("```"):
            text = text.rsplit("```", 1)[1].strip()
        cleaned = json.loads(text)
        return RiskResult(**cleaned)
    except Exception:
        return RiskResult(tier=2, likelihood="unclear", factors=["context unavailable"], remediation="please say more")

def safety_check(text: str) -> SafetyResult:
    text = text.lower()
    hazardous = any(w in text for w in ("kill myself", "take my life", "end it all", "no reason to live", "want die"))
    deny = any(w in text for w in ("kill myself", "take my life", "end it all"))
    cutoff = "immediate human escalation" if deny else "no escalation required yet"
    action = "transfer to human clinician now" if deny else "continue safe loop with follow-up"
    return SafetyResult(hazardous=hazardous, deny=deny, cutoff=cutoff, action=action)

def parse_json_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 1)[1].strip()
    if text.endswith("```"):
        text = text.rsplit("```", 1)[1].strip()
    return json.loads(text)

def next_turn(user_text: str, history: list) -> str:
    """Generate LLM assistant reply and append to history."""
    messages = history + [{"role": "user", "content": user_text}]
    resp = client.chat.completions(messages=messages, model="sarvam-105b")
    return resp.choices[0].message.content

def risk_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 1)[1].strip()
    if text.endswith("```"):
        text = text.rsplit("```", 1)[1].strip()
    try:
        return json.loads(text)
    except Exception:
        return {}

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS conversations (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               timestamp TEXT,
               student_name TEXT,
               student_grade TEXT,
               turn INTEGER,
               user_text TEXT,
               assistant_text TEXT,
               risk_tier INTEGER,
               risk_likelihood TEXT,
               safety_action TEXT,
               education_flag TEXT
            )"""
        )
        conn.commit()

def save_response(
    student_name: str,
    student_grade: Optional[str],
    turn: int,
    user_text: str,
    assistant_text: str,
    risk: dict,
    safety_result: SafetyResult,
) -> None:
    risk_tier_val = risk.get("tier", 1)
    risk_likelihood = risk.get("likelihood", "unknown")
    risk_factors = risk.get("factors", [])
    remediation = risk.get("remediation", "continue conversation")
    danger = safety_result.deny or safety_result.hazardous
    education_flag = "HIGH_RISK" if danger else "NORMAL"
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """INSERT INTO conversations
               (timestamp, student_name, student_grade, turn, user_text, assistant_text,
                risk_tier, risk_likelihood, safety_action, education_flag)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.utcnow().isoformat() + "Z",
                student_name,
                student_grade,
                turn,
                user_text,
                assistant_text,
                risk_tier_val,
                risk_likelihood,
                safety_result.action,
                education_flag,
            ),
        )
        conn.commit()

# ---------------------------------------------------------------------------
# Seed dummy students
# ---------------------------------------------------------------------------
SEED_STUDENTS = [
    {"name": "Priya Sharma", "photo_url": "https://i.pravatar.cc/150?img=32"},
    {"name": "Aryan Nair", "photo_url": "https://i.pravatar.cc/150?img=10"},
    {"name": "Kavya Pillai", "photo_url": "https://i.pravatar.cc/150?img=27"},
    {"name": "Siddharth Rao", "photo_url": "https://i.pravatar.cc/150?img=53"},
    {"name": "Divya Menon", "photo_url": "https://i.pravatar.cc/150?img=20"},
]
GRADE_OPTIONS = ["7", "8", "9", "10", "11", "12"]

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("Saathi")
    if st.checkbox("Student Guide view"):
        st.info("This will show a simplified prompt flow for demo messaging.")
    st.subheader("Student Selector")
    session_state = st.session_state
    if "students" not in session_state:
        session_state.students = SEED_STUDENTS[:]
    student = st.selectbox("Choose student", session_state.students, key="student_selector")
    student_name = f"{student['name']}"
    grade = st.selectbox("Grade", [""] + GRADE_OPTIONS, key="grade_selector")
    test_clip_btn = st.checkbox("Use test clip", key="test_clip")
    if test_clip_btn:
        st.text("Loading test audio…")
        if not TEST_CLIP_PATH or not os.path.exists(TEST_CLIP_PATH):
            st.error("No test clip found; set SAATHI_TEST_CLIP path or disable the checkbox.")
        else:
            session_state.test_audio = TEST_CLIP_PATH
    session_state.grade = grade

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
if not os.environ.get("SAATHI_NOINIT", "").lower() == "true":
    init_db()

# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Saathi", layout="centered")
with st.container():
    header = st.empty()
    if "turn" not in session_state:
        session_state.turn = 0
        session_state.transcript = []
    if "history" not in session_state:
        session_state.history = []
    if "consent" not in session_state:
        session_state.consent = False
    if "consent_time" not in session_state:
        session_state.consent_time = ""
    if "risk_result" not in session_state:
        session_state.risk_result = RiskResult(tier=0, likelihood="none", factors=[], remediation="Begin session")
    if "safety_result" not in session_state:
        session_state.safety_result = SafetyResult(hazardous=False, deny=False, cutoff="no escalation", action="continue")
    if not session_state.consent:
        header.info(
            "**Saathi** is a wellness voice agent.\n"
            "It uses your voice to check in, answers in several Indian languages, and recommends resources.\n\n"
            "Instructions:\n"
            "1. Give consent.\n"
            "2. Choose your language and speak.\n"
            "3. The app listens, responds, and checks for risk.\n"
            "4. Keep the session private; do not mention names of others.\n\n"
            "Risk level is estimated and not a diagnosis. If you are in danger, call emergency services or talk to a trusted adult immediately."
        )
        header.markdown("## Consent required")
        if st.button("I consent and want to continue", type="primary"):
            session_state.consent = True
            session_state.consent_time = datetime.utcnow().isoformat() + "Z"
            header.success("Consent recorded. You may now choose a language and speak.")
    else:
        header.success(f"Welcome, {student_name}! Ready to start.")
        st.markdown("---")
        lang = st.selectbox("Language", ["en", "hi", "ta", "te", "kn"], key="lang")
        audio_input = st.file_uploader("Send voice / upload audio", type=["wav", "ogg", "mp3"], key="upload")
        if audio_input:
            session_state.test_audio = audio_input.name
            session_state.transcript = []
            session_state.turn = 0
            st.info("Test clip loaded. Run transcription, LLM, and TTS in the background if keys are valid.")
        if "test_audio" in session_state:
            result = client.speech_to_text.transcribe(
                file=open(session_state.test_audio, "rb"),
                model="saaras:v4",
                mode="codemix",
            )
            transcript = result.transcript
            session_state.transcript = transcript
            st.info(f"STT output: {transcript[:200]}")
        if "transcript" in session_state and session_state.transcript:
            user_text = session_state.transcript[0] if session_state.transcript else ""
            st.text_input("Edit transcript (optional)", key="edit_transcript", value=user_text)
            user_text = user_text or st.session_state.edit_transcript
            if user_text:
                session_state.turn += 1
                session_state.history.append({"role": "user", "content": user_text})
                with st.spinner("Thinking…"):
                    assistant_text = next_turn(user_text, session_state.history)
                if assistant_text:
                    session_state.history.append({"role": "assistant", "content": assistant_text})
                    save_response(
                        student_name=student_name,
                        student_grade=session_state.grade,
                        turn=session_state.turn,
                        user_text=user_text,
                        assistant_text=assistant_text,
                        risk=session_state.risk_result._dict(),
                        safety_result=session_state.safety_result,
                    )
                    if not session_state.test_audio:
                        text_for_tts = assistant_text[:3000]
                        st.info(f"LLM response set. Use TTS if API key is correct.")
    # -----------------------------------------------------------------------
    # Risk / Safety + sentiment display
    # -----------------------------------------------------------------------
    st_risk = session_state.risk_result
    st_safety = session_state.safety_result
    risk_color = {"green": "green", "amber": "yellow", "red": "red"}[st_risk.tier % 3]
    status = "🟢 green" if st_risk.tier <= 1 else "🟡 amber" if st_risk.tier == 2 else "🔴 red"
    st.markdown("---")
    st.markdown(f"## Status: {status}")
    factors = ", ".join(st_risk.factors) if st_risk.factors else "none"
    st.write(
        f"**Likelihood:** {st_risk.likelihood}  \n"
        f"**Factors:** {factors}  \n"
        f"**Remediation:** {st_risk.remediation}"
    )
    st.markdown("### Safety")
    st.write(f"Assessment: {st_safety.cutoff}  ")
    st.write(f"Action: {st_safety.action}")
    # -----------------------------------------------------------------------
    # Dashboard accordion
    # -----------------------------------------------------------------------
    with st.expander("Dataset & schema"):
        with st.container():
            conn = sqlite3.connect(DB_PATH)
            dc = conn.execute(
                "SELECT * FROM conversations ORDER BY rowid DESC LIMIT 1;"
            ).fetchone()
            if dc:
                cols = [desc[0] for desc in conn.execute("PRAGMA table_info(conversations)").fetchall()]
                df = conn.execute(
                    "SELECT * FROM conversations ORDER BY turn DESC LIMIT 10;"
                ).fetchall()
            conn.close()
            st.json(dict(zip(cols, dc)) if dc else "No rows")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
with st.container():
    st.markdown("---")
    st.markdown(f"Saathi (demo) — timestamp {datetime.utcnow().isoformat()}Z")
