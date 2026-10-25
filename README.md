# Saathi

Saathi is a multilingual wellness voice agent for students.  
It uses voice input to check in, responds in Indian languages, and flags risk with human-reviewed escalation.

## Models used

- **Saaras v4** — speech-to-text (STT)
- **Sarvam-105B** — chat/completion (LLM)
- **Bulbul v3** — text-to-speech (TTS)

## Setup

```bash
pip install -r requirements.txt
export SARVAM_API_KEY="your_key"
streamlit run app.py
```

## Test clips

Set `SAATHI_USE_TEST=true` and provide `SAATHI_TEST_CLIP` pointing to a local audio file (WAV/OGG/MP3).  
Upload a test file in the sidebar and the pipeline will auto-run STT, LLM, and save a row.

## Safety notes

- This is **assistive triage only** — not a medical diagnosis.
- Explicit consent is required before each session.
- Every risky turn is stored in SQLite for **human review**.
- **Red-tier users** see a fixed message with **Tele-MANAS 14416** and are not messaged automatically.
- Real calls, disclaimers, and clinician routing are **not implemented** in this demo.

## Next steps

- Real phone-call integration
- Weekly mood trends
- Anonymised cohort insights
