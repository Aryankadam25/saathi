import os
from sarvamai import SarvamAI
from sarvamai.play import save

client = SarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"])

clips = {
    "clip1_normal": "Is hafte sab theek chal raha hai. Classes achhi ja rahi hain, thoda busy hoon but manage ho jata hai. Neend bhi theek hai.",
    "clip2_stressed": "Yaar thoda stress hai. Mid-sems aa rahe hain, backlog bhi hai. Raat ko neend nahi aati, aur ghar pe bhi pressure hai.",
    "clip3_serious": "Ab kuch kaam nahi kar raha. Sab bahut heavy lagta hai, aur kabhi kabhi lagta hai ki koi fayda hi nahi hai. Kisi se baat karne ka mann bhi nahi karta.",
}

for name, text in clips.items():
    audio = client.text_to_speech.convert(
        text=text,
        model="bulbul:v3",
        language_code="hi-IN",
        speaker="shubh",
    )
    save(audio, f"{name}.wav")
    print("Saved", f"{name}.wav")