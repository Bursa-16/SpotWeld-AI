from fastapi.testclient import TestClient
from app.main import app
client=TestClient(app)

def payload():
    return {"material_family":"Düşük / Orta Karbonlu Çelik","material_subtype":"Düşük karbonlu çelik","stack_count":"2T","layers":[{"material_family":"Düşük / Orta Karbonlu Çelik","material_subtype":"Düşük karbonlu çelik","thickness_mm":1.0,"coated":False},{"material_family":"Düşük / Orta Karbonlu Çelik","material_subtype":"Düşük karbonlu çelik","thickness_mm":1.0,"coated":False}],"current_ka":8.0,"weld_cycles":12,"force_kn":3.0,"tip_diameter_mm":6.0,"squeeze_cycles":15,"hold_cycles":15,"cooling_flow_lpm":6.0,"cooling_temp_c":20,"dc_current":True,"adhesive":False,"shunt_risk":False}

def test_health():
    r=client.get("/api/v1/health"); assert r.status_code==200; assert r.json()["status"]=="ok"

def test_analysis():
    r=client.post("/api/v1/weld-analysis",json=payload()); assert r.status_code==200
    b=r.json(); assert b["nugget_min_mm"]==4.2; assert b["selected_model"]=="OEM Referans Tablosu"
