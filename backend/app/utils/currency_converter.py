from typing import Optional

def convert_to_rub(value: float, currency: str, exchange_rate: Optional[float]) -> float:
    if currency == "USD" and exchange_rate:
        return value * exchange_rate
    return value