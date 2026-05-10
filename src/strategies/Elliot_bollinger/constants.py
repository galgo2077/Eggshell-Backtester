"""
Antigravity Systems — Elliott Wave Bollinger Constants
"""

EMA_FAST   = 10   
EMA_MEDIUM = 20   
EMA_SLOW   = 50   

BOLLINGER_SD_RATIO = 0.05  

PIVOT_WINDOW_DIVISOR   = 25  
PIVOT_MIN_DIST_DIVISOR = 15  

SYSTEM_PROMPT_1_TEMPLATE = """
You are an expert quantitative Elliott Wave analyst specializing in swing pivot detection.

TASK: Optimize wave parameters for {active_wave_desc} using the close price history below.

Close price history ({llm_total} bars, oldest to newest):
{llm_prices}

Recent high prices (last {recent_n} bars): {recent_high}
Recent low  prices (last {recent_n} bars): {recent_low}

Parameters to optimize:
- A  (Base Amplitude / Wave 1 height): current = {curr_A}
- r2 (Wave 2 retracement ratio):       current = {curr_r2}

CRITICAL ELLIOTT WAVE RULES (MUST BE STRICTLY ENFORCED):
1. Wave 2 retracement r2: 0.382 ≤ r2 ≤ 0.786 (CANNOT exceed Wave 1 origin - 100% max retrace).
2. Wave 3 MUST be >= Wave 1 AND >= Wave 5 (Wave 3 can NEVER be the shortest).
3. Wave 4 CANNOT overlap Wave 1 territory (price must stay above Wave 1 origin in bullish).
4. Identify actual swing pivots in the price data.

Return ONLY this JSON (no extra text):
{{"reasoning": "brief step-by-step math explaining pivot detection and rule validation", "A": float_0.2_to_3.0, "r2": float_0.38_to_0.786, "rules_valid": true_or_false}}
"""

