from services.higgins.di_record import aggregate_usage

def test_unknown_tokens_and_cost_remain_unknown():
    result = aggregate_usage([{"processing": {"geminiCalls": 1}}], [])
    assert result["providerCalls"] == 1
    assert result["inputTokens"] is None and result["reasoningTokens"] is None
    assert result["cost"]["amountUsd"] is None

def test_reported_tokens_sum_and_estimates_remain_labelled():
    row = {"processing": {"geminiCalls": 1, "promptTokens": 100, "outputTokens": 10, "reasoningTokens": 20, "cost": {"amountUsd": 0.01, "basis": "estimated"}}}
    result = aggregate_usage([row, row], [{"status": "completed"}])
    assert result["inputTokens"] == 200 and result["reasoningTokens"] == 40
    assert result["cost"] == {"amountUsd": 0.02, "basis": "estimated"}
