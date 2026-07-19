# Engineering Models v0.9

## Weld Lobe
Current-time grid is evaluated using a surrogate nugget model.
Each point is classified into:
- Yetersiz Füzyon
- Güvenli
- Uyarı
- Expulsion Riski

## Pulse Strategy
Decision score considers:
- material family
- coating
- thickness ratio
- stack count
- adhesive
- weld time

## Electrode Life
Starting factors:
- material family
- coating
- cooling flow
- cooling temperature
- current
- tip diameter

## Dynamic Resistance
Extracted features:
- initial resistance
- peak resistance
- peak index
- final resistance
- post-peak drop
- overall slope

All models require customer-specific calibration before production release.
