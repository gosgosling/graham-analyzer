

def classify_company(multipliers):

    """
    Классифицирует компанию на основе мультипликаторов по принципам Грэма.
    
    Args:
        multipliers: словарь с мультипликаторами компании
            - pe_ratio: Price-to-Earnings
            - pb_ratio: Price-to-Book
            - debt_to_equity: отношение долга к собственному капиталу
            - current_ratio: коэффициент текущей ликвидности
            - roe: Return on Equity (%)
            - dividend_yield: дивидендная доходность (%)
    
    Returns:
        dict: словарь с классификацией и статусами показателей
            - classify: "undervalued", "stable" или "overvalued"
            - pe_ratio_status: "good", "normal" или "bad"
            - pb_ratio_status: "good", "normal" или "bad"
            - debt_status: "good", "normal" или "bad"
            - liquidity_status: "good", "normal" или "bad"
            - profitability_status: "good", "normal" или "bad"
    """
    pe = multipliers['pe_ratio']
    pb = multipliers['pb_ratio']
    debt_to_equity = multipliers['debt_to_equity']
    current_ratio = multipliers['current_ratio']
    roe = multipliers['roe']
    dividend_yield = multipliers['dividend_yield']

    pe_ratio_status = _evaluate_status(pe, 15, 25, is_higher_better=False)
    pb_ratio_status = _evaluate_status(pb, 1.5, 3.0, is_higher_better=False)
    debt_status = _evaluate_status(debt_to_equity, 0.5, 1.0, is_higher_better=False)
    profitability_status = _evaluate_status(roe, 15, 10, is_higher_better=True)
    liquidity_status = _evaluate_status(current_ratio, 2.0, 1.5, is_higher_better=True)

    classify = ""
    
    is_undervalued = (pe < 15 and pb < 1.5 and debt_to_equity <= 0.5 and current_ratio > 2.0 and roe > 15 and dividend_yield > 3)
    is_stable = ( 15 <= pe <= 25 and 1.5 <= pb <= 3.0 and debt_to_equity < 1 and current_ratio > 1.5 and roe > 10 and dividend_yield > 3)  
    if is_undervalued: classify = "undervalued"
    elif is_stable: classify = "stable"
    else: classify = "overvalued"
    result = {
        "classify": classify,
        "pe_ratio_status": pe_ratio_status,  # good/bad/neutral
        "pb_ratio_status": pb_ratio_status,
        "debt_status": debt_status,
        "liquidity_status": liquidity_status,
        "profitability_status": profitability_status
        
    }   

    """meets_pe_criteria = pe < 15
    meets_pb_criteria = pb < 1.5
    meets_debt_criteria = debt_to_equity <= 0.5
    meets_liquidity_criteria = current_ratio > 2.0
    meets_profitability_criteria = roe > 15
    meets_dividend_criteria = dividend_yield > 3

    is_undervalued = (
        meets_pe_criteria and 
        meets_pb_criteria and 
        meets_debt_criteria and 
        meets_liquidity_criteria and 
        meets_profitability_criteria and 
        meets_dividend_criteria
    )"""

    return result
    

def _evaluate_status(value, good_threshold, normal_threshold, is_higher_better=True):
    """
    Оценивает статус показателя
    
    Args:
        value: значение показателя
        good_threshold: порог для "good"
        normal_threshold: порог для "normal"
        is_higher_better: True если больше = лучше (для ROE, current_ratio)
                         False если меньше = лучше (для P/E, P/B, debt)
    """
    if is_higher_better:
        if value >= good_threshold:
            return "good"
        elif value >= normal_threshold:
            return "normal"
        else:
            return "bad"
    else:
        if value <= good_threshold:
            return "good"
        elif value <= normal_threshold:
            return "normal"
        else:
            return "bad"