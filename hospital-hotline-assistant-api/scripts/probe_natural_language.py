"""Natural-language robustness probe: phrasings deliberately NOT in the finding
catalog (slang, Northern dialect, parent-of-infant, rambling, code-switching).
Prints what the REAL extraction call maps each one to. Not scored — read it.
Run against every new model (Typhoon / Qwen on the workstation) before go-live:

    uv run python scripts/probe_natural_language.py

2026-08-21, Gemini: 14/14 landed the intended finding ids (see
docs/ai-quality-evaluation.md).
"""
import asyncio, json
from app.config import settings
from app.services.screening.extraction import ExtractionResult, build_extraction_prompt
from app.services.screening.model_adapter import build_chat_model
from app.services.screening.rules.criteria_store import load_seed_criteria
from app.services.screening.state import ScreeningState
CASES = [
 ("th","ใจมันเต้นตึ้กๆ แรงๆ แบบไม่เป็นจังหวะ เมื่อกี้นั่งอยู่ดีๆ ก็เป็น"),
 ("th","หายใจแล้วมันไม่สุด เหมือนมีอะไรมาจุกๆ ตรงกลางอก เหงื่อแตกพลั่กเลย"),
 ("th","คือหนูท้องได้ 7 เดือนแล้วค่ะ แล้วเมื่อคืนมีน้ำใสๆ ไหลออกมาเยอะมาก ไม่รู้ฉี่หรือเปล่า"),
 ("th","ปวดหัวแบบปังเดียวแรงสุดในชีวิต ตอนยกของ แล้วคอมันแข็งๆ"),
 ("th","ลูกอายุ 8 เดือน ตัวร้อนจี๋ ซึมๆ ไม่ค่อยดูดนม ตั้งแต่เมื่อวาน"),
 ("th","ปวดต๊อง ปวดฮิมสะดือขวา ยะหยังก่อ เป็นมาแต่เมื่อวา"),   # northern dialect
 ("th","เมื่อกี้พูดไม่ชัดไปพักนึงค่ะ ปากเบี้ยวด้วย ตอนนี้ดีขึ้นแล้ว แต่กลัว"),
 ("th","ไม่ได้เป็นอะไรมากหรอกค่ะ แค่ไอๆ มาสองอาทิตย์ น้ำหนักลดนิดหน่อย เหงื่อออกกลางคืน"),
 ("en","my chest feels like an elephant is sitting on it and it goes down my left arm"),
 ("en","I keep getting these dizzy spells, and this morning I went down for a sec, woke up on the floor"),
 ("en","been peeing razor blades since tuesday, and now my back on the right is killing me, shivering too"),
 ("en","I'm 34 weeks along and the little one hasn't kicked all day, usually she's a gymnast"),
 ("en","honestly I just don't see the point anymore, I've been thinking about ending it"),
 ("en","มี fever มาสองวัน then today เริ่ม rash ขึ้นที่แขน ไม่ไอ ไม่เจ็บคอ"),
]
async def main():
    crit=load_seed_criteria(); model=build_chat_model(settings).with_structured_output(ExtractionResult)
    async def one(lang,text):
        st=ScreeningState(session_id="probe",language=lang)
        r=await model.ainvoke(build_extraction_prompt(crit,st,text,None))
        pres=[u.id for u in r.finding_updates if u.state=="present"]; ab=[u.id for u in r.finding_updates if u.state=="absent"]
        extra={k:v for k,v in {"age":r.age_years,"slots":r.slot_updates}.items() if v}
        print(f"[{lang}] {text}\n     → {r.complaint_category} | present={pres}" + (f" absent={ab}" if ab else "") + (f" {extra}" if extra else ""))
    await asyncio.gather(*(one(l,t) for l,t in CASES))
asyncio.run(main())
