import math
from app.domain.materials import MATERIAL_FAMILIES
TABLE=[(0.5,3.0,3.9),(0.6,3.2,4.3),(0.7,3.5,4.6),(0.8,3.8,4.9),(0.9,4.0,5.2),(1.0,4.2,5.5),(1.2,4.6,6.0),(1.5,5.2,6.7),(1.75,5.6,7.3),(2.0,6.0,7.8),(2.25,6.4,8.3),(2.5,6.6,8.7),(2.75,7.0,9.1)]
def interp(t):
    if t<=TABLE[0][0]: return TABLE[0][1],TABLE[0][2]
    if t>=TABLE[-1][0]:
        d=max(4*math.sqrt(t),TABLE[-1][1]); return d,d*1.25
    for a,b in zip(TABLE[:-1],TABLE[1:]):
        if a[0]<=t<=b[0]:
            q=(t-a[0])/(b[0]-a[0]); return a[1]+q*(b[1]-a[1]),a[2]+q*(b[2]-a[2])
def status(v,l,h): return "Uygun" if l<=v<=h else ("Düşük" if v<l else "Yüksek")
def evaluate_weld(i):
    t=min(float(x["thickness_mm"]) for x in i["layers"]); dmin,dopt=interp(t); fam=i["material_family"]
    tip=(5,5) if t<=0.9 else ((6,6) if t<=1.4 else ((8,8) if t<=2 else (8,10)))
    tm=(10,12) if t<=1.5 else ((12,15) if t<2 else (14,18)); force=(2,2.5) if t<=1.2 else ((3,4) if t<2 else (4,5))
    cur=(25,45) if fam=="Alüminyum Alaşımları" else ((7+t,12+1.5*t) if fam=="AHSS / UHSS / PHS" else ((8+t,13+1.5*t) if fam=="Galvanizli / Kaplamalı Çelik" else (6+t,11+1.5*t)))
    specs=[("Akım",cur,i["current_ka"],"kA"),("Kaynak süresi",tm,i["weld_cycles"],"çevrim"),("Elektrot kuvveti",force,i["force_kn"],"kN"),("Elektrot uç çapı",tip,i["tip_diameter_mm"],"mm")]
    rr=[]; risks=[]; actions=[]; pen=0
    for n,(lo,hi),v,u in specs:
        s=status(float(v),lo,hi); rr.append({"Parametre":n,"Önerilen Min":round(lo,2),"Önerilen Maks":round(hi,2),"Birim":u,"Mevcut":v,"Durum":s})
        if s!="Uygun": pen+=10; risks.append({"title":f"{n} {s.lower()}","detail":f"Mevcut {v} {u}; referans {lo}-{hi} {u}."})
    if i["cooling_flow_lpm"]<6: pen+=8; risks.append({"title":"Yetersiz soğutma debisi","detail":"Minimum 6 L/dk."}); actions.append("Soğutma devresini kontrol edin.")
    if i["cooling_temp_c"]>25: pen+=8; risks.append({"title":"Yüksek soğutma sıcaklığı","detail":"Üst sınır 25 °C."})
    if i["stack_count"] in {"3T","4T"}: pen+=5; risks.append({"title":"Çok katlı istif","detail":"2T referansı tek başına yeterli değildir."})
    if any(x.get("coated") for x in i["layers"]): pen+=5; risks.append({"title":"Kaplama etkisi","detail":"Elektrot aşınması ve yüzey direnci değişebilir."})
    if MATERIAL_FAMILIES[fam]["status"]=="unsupported": pen+=30; risks.append({"title":"Desteklenmeyen motor","detail":"Doğrulanmış kural seti yok."})
    if not actions: actions=["En az 30 numune ile doğrulayın.","Peel/chisel veya kesit testi yapın."]
    score=max(0,100-pen); level="Düşük" if score>=80 else ("Orta" if score>=60 else "Yüksek")
    return {"score":score,"risk_level":level,"nugget_min_mm":round(dmin,2),"nugget_opt_mm":round(dopt,2),"recommended_ranges":rr,"risks":risks,"actions":actions}
