import os, sys, json, urllib.request
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
load_dotenv(os.path.join(os.getcwd(), ".env"))
from jose import jwt
from app.database import SessionLocal
from app.models import User

db = SessionLocal()
u = db.query(User).filter(User.email == "dvertel@sfisas.com").first() or db.query(User).first()
token = jwt.encode({"sub": u.email, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
                   os.getenv("SECRET_KEY"), algorithm=os.getenv("ALGORITHM", "HS256"))

def get(url):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

corr = get("http://localhost:5000/questions/question-table-relation/answers/949?only_latest=true")
valor = corr.get("latest_answer")
rid = (corr.get("correlations") or {}).get(valor, {}).get("__response_id__")
print("valor:", valor, "| envio de origen:", rid)

d = get(f"http://localhost:5000/questions/serial-autofill/{rid}?target_form_id=525")
print("campos sueltos :", json.dumps(d.get("answers_by_local_question_id"), ensure_ascii=False)[:250])
print("filas repetidor:", json.dumps(d.get("repeater_rows_local"), ensure_ascii=False)[:300])
db.close()
