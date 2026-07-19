from dataclasses import dataclass
from typing import Optional
import math

@dataclass
class ModelResult:
    model_name: str
    prediction_mm: Optional[float]
    confidence: str
    status: str
    note: str

def minitab_doe_predict(v):
    req=["current_a","force_dan","time_cycle","cooling_cycle","sequence_cycle","holding_cycle","sheet_thickness_mm"]
    miss=[k for k in req if v.get(k) is None]
    if miss: return ModelResult("Minitab DOE",None,"Düşük","Eksik veri",", ".join(miss))
    C,F,T,Co,Sq,H,St=[float(v[k]) for k in req]
    y=-70.3+0.01390*C-0.1678*F-1.799*T+10.25*Co+0.891*Sq+4.156*H-19.72*St
    return ModelResult("Minitab DOE",round(y,3),"Düşük","Deneysel / doğrulanmamış","Birimler A, daN, çevrim ve mm kabul edildi.")

def oem_table_prediction(dmin,dopt):
    return ModelResult("OEM Referans Tablosu",round(dopt,3),"Orta","Referans",f"Minimum: {dmin:.2f} mm")

def literature_4sqrt_t(t):
    return ModelResult("4√t Literatür Kriteri",round(4*math.sqrt(t),3),"Orta","Minimum kriter","En ince sac esas alındı.")
