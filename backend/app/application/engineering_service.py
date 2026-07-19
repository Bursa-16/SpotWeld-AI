
from __future__ import annotations

from app.domain.dynamic_resistance import analyze_dynamic_resistance
from app.domain.electrode_life import estimate_electrode_life, build_stepper_profile
from app.domain.pulse_strategy import recommend_pulse_strategy
from app.domain.sensitivity import parameter_sensitivity
from app.domain.weld_lobe import generate_weld_lobe, estimate_nugget


class EngineeringService:
    def weld_lobe(self, payload):
        result = generate_weld_lobe(**payload.model_dump())

        optimum = result.get("optimum")
        if optimum:
            base = {
                "current_ka": optimum["current_ka"],
                "weld_cycles": optimum["weld_cycles"],
                "force_kn": payload.force_kn,
            }

            result["sensitivity"] = parameter_sensitivity(
                base,
                lambda values: estimate_nugget(
                    payload.material_family,
                    payload.thickness_mm,
                    values["current_ka"],
                    values["weld_cycles"],
                    values["force_kn"],
                ),
            )
        else:
            result["sensitivity"] = []

        return result

    def pulse_strategy(self, payload):
        return recommend_pulse_strategy(**payload.model_dump())

    def electrode_life(self, payload):
        values = payload.model_dump()
        stepper_end = values.pop("stepper_end_current_ka")
        result = estimate_electrode_life(**values)

        end_current = stepper_end or round(payload.current_ka * 1.15, 2)
        result["stepper_profile"] = build_stepper_profile(
            initial_current_ka=payload.current_ka,
            end_current_ka=end_current,
            electrode_life_spots=result["estimated_life_spots"],
        )
        return result

    def dynamic_resistance(self, payload):
        return analyze_dynamic_resistance(payload.samples_micro_ohm)
