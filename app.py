import os, json, re, sqlite3, tempfile, datetime
import streamlit as st
import pandas as pd
from sarvamai import SarvamAI
from sarvamai.play import save

st.set_page_config(page_title="Saathi", page_icon="🎙️", layout="wide")
KEY = os.environ.get("SARVAM_API_KEY")
if not KEY:
    st.error("Set the SARVAM_API_KEY environment variable and restart.")
    st.stop()
client = SarvamAI(api_subscription_key=KEY)
ss = st.session_state

RANK = {"green": 0, "amber": 1, "red": 2}
ICON = {"green": "🟢", "amber": "🟡", "red": "🔴"}
OPENER = ("Namaste! Main Saathi hoon, ek AI assistant. Aapke Student Guide ko is check-in ka summary dikhega. "
          "Aap Hindi, Marathi ya English mein baat kar sakte hain. Is hafte kaisa raha?")
RED_MSG = ("Aapne jo bataya, wo bahut maayne rakhta hai, aur main nahi chahta ki aap akele rahein. "
           "Aapke Student Guide ko aapse baat karne ke liye abhi bataya ja raha hai. "
           "Agar aap abhi bahut pareshaan hain, to kisi bharosemand insaan se baat karein "
           "ya Tele-MANAS helpline 14416 par call karein.")
# Extend these patterns (Hindi, Marathi, English, romanized). They can only RAISE the risk tier.
RED_PATTERNS = [
    r"fayd[ae]\s+(hi\s+)?nahi", r"फ़?ायदा\s+(ही\s+)?नहीं", r"फ़ायदा\s+(ही\s+)?नहीं",
    r"jeen[ae]\s+(ka\s+mann\s+)?nahi", r"जीने\s+का\s+मन\s+नहीं", r"जीना\s+नहीं",
    r"mar\s*jau", r"marna\s+chah", r"मर\s*जा", r"मरना\s+चा",
    r"sab\s+khatam", r"सब\s+खत्म",
    r"upyog\s+nahi", r"उपयोग\s+नाही", r"jagavasa\s+vatat\s+nahi", r"मरावंसं", r"maravasa",
    r"suicide", r"kill myself", r"end (it all|my life)", r"want to die", r"no point", r"hopeless", r"can'?t go on",
]
AGENT_SYS = ("You are Saathi, a warm AI wellness check-in assistant for college students in India. "
             "The greeting already asked how their week was. Reply in the same language and style the student used "
             "(Hindi, Marathi, English or Hinglish). Maximum 2 short, kind sentences. Ask at most one gentle question. "
             "Never diagnose, never give medical advice, never mention hotlines.")
TURN_HINT = ["Next, gently ask about their sleep or how they have been feeling.",
             "Next, gently ask about academic pressure and who they can talk to.",
             "This is the last turn: thank them warmly, say their Student Guide is there to help. Ask no question."]
ANALYSIS_PROMPT = ("You help a college Wellness Council triage a student wellness check-in. Read the student's words and return "
                   "ONLY a JSON object with keys: stress_score (integer 1-5), themes (list of short English strings), "
                   "risk_tier (one of green, amber, red), key_quote (a short exact quote from the student), "
                   "english_summary (2 neutral sentences in English, no diagnosis). If unsure between two tiers, choose the higher one.")

# ---------- database ----------
def db():
    c = sqlite3.connect("saathi.db")
    c.execute("""CREATE TABLE IF NOT EXISTS checkins(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, ts TEXT,
                 tier TEXT, stress INTEGER, themes TEXT, quote TEXT, summary TEXT, transcript TEXT)""")
    return c

def seed():
    c = db()
    if c.execute("SELECT COUNT(*) FROM checkins").fetchone()[0] == 0:
        rows = [
            ("Asha (demo)", "2026-10-19 10:00", "green", 1, "settled, good routine", "Sab theek chal raha hai.", "Student reports a stable week and good sleep.", "Sab theek chal raha hai."),
            ("Rohan (demo)", "2026-10-19 10:20", "amber", 4, "exams, sleep", "Raat ko neend nahi aati.", "Student is anxious about mid-sems and sleeping poorly.", "Mid-sems ka stress hai, neend nahi aati."),
            ("Meera (demo)", "2026-10-20 09:40", "green", 2, "workload", "Thoda busy hoon but manage ho jata hai.", "Student is busy but coping well.", "Thoda busy hoon but manage ho jata hai."),
            ("Kabir (demo)", "2026-10-21 11:05", "amber", 3, "family pressure, backlog", "Ghar pe bhi pressure hai.", "Student mentions backlog and pressure from home.", "Backlog hai aur ghar pe pressure hai."),
            ("Sneha (demo)", "2026-10-22 16:30", "red", 5, "withdrawal, hopelessness", "Koi fayda hi nahi hai.", "Student sounds hopeless and withdrawn. Needs a human follow-up soon.", "Sab heavy lagta hai, koi fayda nahi."),
        ]
        c.executemany("INSERT INTO checkins(name,ts,tier,stress,themes,quote,summary,transcript) VALUES(?,?,?,?,?,?,?,?)", rows)
        c.commit()
    c.close()

# ---------- Sarvam calls ----------
def stt(wav_bytes):
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as t:
        t.write(wav_bytes)
        path = t.name
    try:
        with open(path, "rb") as f:
            r = client.speech_to_text.transcribe(file=f, model="saaras:v4", mode="codemix")
    finally:
        os.remove(path)
    return (r.transcript or "").strip(), getattr(r, "language_code", None)

def tts_lang(code):
    c = (code or "hi-IN").lower()
    return "mr-IN" if c.startswith("mr") else "en-IN" if c.startswith("en") else "hi-IN"

def tts(text, lang):
    audio = client.text_to_speech.convert(text=text[:900], model="bulbul:v3", language_code=lang, speaker="shubh")
    path = os.path.join(tempfile.gettempdir(), f"saathi_{datetime.datetime.now().timestamp()}.wav")
    save(audio, path)
    return path

def llm(messages):
    r = client.chat.completions(model="sarvam-105b", messages=messages)
    out = r.choices[0].message.content or ""
    return re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()

# ---------- risk logic ----------
def parse_json(s):
    try:
        return json.loads(s[s.index("{"): s.rindex("}") + 1])
    except Exception:
        return {}

def red_flag(text):
    return any(re.search(p, text, flags=re.I) for p in RED_PATTERNS)

def analyse():
    transcript = "\n".join(t for r, t in ss.chat if r == "user")
    d = parse_json(llm([{"role": "system", "content": ANALYSIS_PROMPT}, {"role": "user", "content": transcript}]))
    tier = d.get("risk_tier") if d.get("risk_tier") in RANK else "amber"  # parse failure -> amber
    if red_flag(transcript):
        tier = "red"  # rules can only raise
    try:
        stress = max(1, min(5, int(d.get("stress_score", 3))))
    except Exception:
        stress = 3
    themes = ", ".join(map(str, d.get("themes", []))) if isinstance(d.get("themes"), list) else ""
    res = dict(name=ss.get("name") or "Student", ts=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), tier=tier,
               stress=stress, themes=themes, quote=str(d.get("key_quote", "")),
               summary=str(d.get("english_summary", "Summary unavailable; please review the transcript.")), transcript=transcript)
    c = db()
    c.execute("INSERT INTO checkins(name,ts,tier,stress,themes,quote,summary,transcript) VALUES(?,?,?,?,?,?,?,?)",
              (res["name"], res["ts"], res["tier"], res["stress"], res["themes"], res["quote"], res["summary"], res["transcript"]))
    c.commit()
    c.close()
    return res

def process(wav):
    with st.spinner("Samajh raha hoon..."):
        text, code = stt(wav)
        if not text:
            st.warning("Kuch sunai nahi diya, dobara try karein.")
            return
        ss.chat.append(("user", text))
        ss.lang = tts_lang(code)
        msgs = [{"role": "system", "content": AGENT_SYS + " " + TURN_HINT[ss.turn]}]
        msgs += [{"role": "user" if r == "user" else "assistant", "content": t} for r, t in ss.chat[1:]]
        reply = llm(msgs) or "Shukriya batane ke liye. Main sun raha hoon."
        ss.chat.append(("assistant", reply))
        ss.turn += 1
        speak = reply
        if ss.turn == 3:
            ss.result = analyse()
            ss.done = True
            if ss.result["tier"] == "red":
                speak, ss.lang = RED_MSG, "hi-IN"
        ss.audio = tts(speak, ss.lang)
        ss.autoplay = True
    st.rerun()

# ---------- UI ----------
seed()
view = st.sidebar.radio("View", ["Student check-in", "Student Guide view"])
src = st.sidebar.radio("Audio input", ["Microphone", "Use test clip"])

if view == "Student check-in":
    st.title("🎙️ Saathi: weekly wellness check-in")
    for k, v in dict(turn=0, chat=[("assistant", OPENER)], done=False, audio=None, autoplay=False, lang="hi-IN", result=None).items():
        ss.setdefault(k, v)
    st.text_input("Name", value="Student", key="name")
    if not st.checkbox("I understand Saathi is an AI, my Student Guide can see a summary, and I can stop anytime."):
        st.stop()
    for role, text in ss.chat:
        with st.chat_message("assistant" if role == "assistant" else "user"):
            st.write(text)
    if ss.audio:
        try:
            st.audio(ss.audio, autoplay=ss.autoplay)
        except TypeError:
            st.audio(ss.audio)
        ss.autoplay = False
    if ss.done and ss.result:
        r = ss.result
        st.subheader(f"Check-in complete {ICON[r['tier']]} {r['tier'].upper()}")
        if r["tier"] == "red":
            st.error(RED_MSG)
        st.caption("Your Student Guide can now see the summary.")
        if st.button("Start a new check-in"):
            for k in ["turn", "chat", "done", "audio", "autoplay", "lang", "result"]:
                ss.pop(k, None)
            st.rerun()
    elif ss.turn < 3:
        a = (st.audio_input("Speak", key=f"mic{ss.turn}") if src == "Microphone"
             else st.file_uploader("Upload a test .wav clip", type=["wav"], key=f"up{ss.turn}"))
        if a is not None:
            try:
                process(a.getvalue())
            except Exception as e:
                st.error(f"Something went wrong: {e}")
else:
    st.title("Student Guide dashboard")
    c = db()
    df = pd.read_sql_query("SELECT * FROM checkins", c)
    c.close()
    df["rank"] = df["tier"].map(RANK)
    df = df.sort_values(["rank", "ts"], ascending=[False, False])
    df["Risk"] = df["tier"].map(ICON) + " " + df["tier"]
    a, b, c3 = st.columns(3)
    a.metric("Check-ins", len(df))
    b.metric("Red", int((df.tier == "red").sum()))
    c3.metric("Amber", int((df.tier == "amber").sum()))
    st.dataframe(df[["Risk", "name", "stress", "themes", "quote", "summary", "ts"]], hide_index=True)
    for _, row in df.iterrows():
        with st.expander(f"{ICON[row['tier']]} {row['name']} · {row['ts']}"):
            st.write("**Summary:**", row["summary"])
            st.write("**Key quote:**", row["quote"])
            st.write("**Transcript:**", row["transcript"])