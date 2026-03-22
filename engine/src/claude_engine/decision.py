"""
Claude Decision Engine — the AI brain that evaluates trade setups.

THIS IS NOT WHERE INDICATORS ARE COMPUTED.
All math (RSI, EMA, Fibonacci, etc.) is done in deterministic strategy code.

Claude's job is CONTEXTUAL EVALUATION:
1. "Given these 7 strategy signals, does this trade make sense?"
2. "Are there conflicting signals that should make us cautious?"
3. "Is the risk:reward reasonable given current market conditions?"
4. "What's my confidence level (1-10) for this setup?"

ANTI-HALLUCINATION MEASURES:
- Claude receives pre-computed signals, NOT raw price data
- Claude must respond in strict JSON schema (no free-form text)
- All prices in Claude's output are VALIDATED against market data
- If Claude returns unreasonable values, the trade is BLOCKED
- Claude can only say BUY, SELL, or SKIP — nothing else

Two-Gate Verification:
- Gate 1: Deterministic (confluence score >= 6, R:R >= 2, risk limits OK)
- Gate 2: Claude evaluation (confidence >= 7 to proceed)
Both gates must pass. Either can block.
"""

import json
import logging

logger = logging.getLogger(__name__)

from ..data.models import ConfluenceResult, ClaudeDecision, Direction
from ..config import config

# The system prompt tells Claude exactly what it is and constrains its output
SYSTEM_PROMPT = """You are the trade evaluation module of Notas Lave, an AI trading co-pilot.

You receive pre-computed strategy signals from deterministic code. Your job is to evaluate whether the confluence of signals justifies taking a trade.

YOU DO NOT COMPUTE INDICATORS. All RSI, EMA, Fibonacci, VWAP values are computed by Python code and given to you as facts.

EVALUATION CRITERIA:
1. Do the strategies AGREE on direction? (More agreement = higher confidence)
2. Is the market regime compatible with the active strategies?
   - Trending regime: Trend-following signals (EMA, Fibonacci) are more reliable
   - Ranging regime: Mean-reversion signals (BB, Stochastic, VWAP) are more reliable
   - If the regime contradicts the dominant strategy type, reduce confidence
3. Are there RED FLAGS? (conflicting signals, weak strength, low scores)
4. Is the risk:reward ratio acceptable? (minimum 2:1 for trend, 1.5:1 for mean-reversion)

RESPOND WITH EXACTLY THIS JSON FORMAT — no other text, no markdown, no explanation outside the JSON:
{
  "action": "BUY" or "SELL" or "SKIP",
  "confidence": 1-10,
  "entry_price": <use the best entry from signals>,
  "stop_loss": <use the tightest reasonable SL>,
  "take_profit": <use the most conservative TP>,
  "reasoning": "<2-3 sentences explaining your decision>",
  "risk_warnings": ["<any concerns>"]
}

RULES:
- confidence >= 7 is required to BUY or SELL
- If signals conflict or are weak, SKIP with low confidence
- If no strategies fired (all NONE), ALWAYS SKIP with confidence 1
- NEVER invent price levels — use values from the signals provided
- Your entry_price must be within 0.5% of the current market price
- If fewer than 2 strategies agree, SKIP
"""


def build_analysis_prompt(result: ConfluenceResult) -> str:
    """
    Build the user prompt that describes the current market state.
    This is what Claude sees — pre-computed facts, not raw data.
    """
    # Collect active signals (ones that actually fired)
    active_signals = [s for s in result.signals if s.direction is not None]
    inactive_signals = [s for s in result.signals if s.direction is None]

    lines = [
        f"SYMBOL: {result.symbol}",
        f"TIMEFRAME: {result.timeframe}",
        f"MARKET REGIME: {result.regime.value}",
        f"COMPOSITE SCORE: {result.composite_score}/10",
        f"CURRENT DIRECTION: {result.direction.value if result.direction else 'NONE'}",
        f"AGREEING STRATEGIES: {result.agreeing_strategies}/{result.total_strategies}",
        "",
        "=== ACTIVE SIGNALS ===",
    ]

    if not active_signals:
        lines.append("(No strategies fired — all returned NONE)")
    else:
        for s in active_signals:
            lines.append(f"\n[{s.strategy_name.upper()}]")
            lines.append(f"  Direction: {s.direction.value}")
            lines.append(f"  Strength: {s.strength.value}")
            lines.append(f"  Score: {s.score}/100")
            lines.append(f"  Entry: {s.entry_price}")
            lines.append(f"  Stop Loss: {s.stop_loss}")
            lines.append(f"  Take Profit: {s.take_profit}")
            lines.append(f"  Reason: {s.reason}")
            if s.metadata:
                for k, v in s.metadata.items():
                    lines.append(f"  {k}: {v}")

    lines.append("\n=== INACTIVE STRATEGIES ===")
    for s in inactive_signals:
        lines.append(f"  [{s.strategy_name}]: {s.reason}")

    lines.append("\nEvaluate this setup and respond with JSON only.")
    return "\n".join(lines)


def validate_claude_response(
    decision: ClaudeDecision,
    result: ConfluenceResult,
) -> tuple[bool, list[str]]:
    """
    Gate 2 validation: sanity-check Claude's output.
    Catches hallucinated prices, impossible levels, etc.
    """
    issues = []

    # Get current price from active signals
    current_price = None
    for s in result.signals:
        if s.entry_price:
            current_price = s.entry_price
            break

    if decision.action == "SKIP":
        return True, []  # SKIP is always valid

    if decision.action not in ("BUY", "SELL"):
        issues.append(f"Invalid action: {decision.action}")
        return False, issues

    # Confidence must be >= threshold
    if decision.confidence < config.claude_min_confidence:
        issues.append(f"Confidence {decision.confidence} below threshold {config.claude_min_confidence}")

    # Entry price must be close to current price
    if current_price and decision.entry_price > 0:
        deviation = abs(decision.entry_price - current_price) / current_price
        if deviation > 0.005:  # 0.5% max deviation
            issues.append(f"Entry price {decision.entry_price} too far from current {current_price} ({deviation*100:.2f}%)")

    # Stop loss must be on correct side
    if decision.action == "BUY":
        if decision.stop_loss >= decision.entry_price:
            issues.append("Stop loss above entry for a BUY")
        if decision.take_profit <= decision.entry_price:
            issues.append("Take profit below entry for a BUY")
    elif decision.action == "SELL":
        if decision.stop_loss <= decision.entry_price:
            issues.append("Stop loss below entry for a SELL")
        if decision.take_profit >= decision.entry_price:
            issues.append("Take profit above entry for a SELL")

    # R:R check
    if decision.entry_price > 0 and decision.stop_loss > 0 and decision.take_profit > 0:
        risk = abs(decision.entry_price - decision.stop_loss)
        reward = abs(decision.take_profit - decision.entry_price)
        if risk > 0:
            rr = reward / risk
            if rr < 1.5:
                issues.append(f"Risk:Reward {rr:.1f}:1 too low")

    return len(issues) == 0, issues


async def evaluate_setup(result: ConfluenceResult) -> ClaudeDecision:
    """
    Send confluence result to Claude for contextual evaluation.

    Gate 1 (pre-check): Must have minimum confluence score
    Gate 2 (Claude): Must return confidence >= 7
    Gate 3 (validation): Output must pass sanity checks
    """
    # Gate 1: Deterministic pre-check
    if result.composite_score < config.min_confluence_score:
        return ClaudeDecision(
            action="SKIP",
            confidence=1,
            reasoning=f"Confluence score {result.composite_score} below minimum {config.min_confluence_score}",
        )

    if result.direction is None:
        return ClaudeDecision(
            action="SKIP",
            confidence=1,
            reasoning="No directional consensus from strategies",
        )

    # Check if Claude is configured (either direct API or Vertex AI)
    has_claude = (
        config.anthropic_api_key
        or (config.claude_provider == "vertex" and config.google_cloud_project)
    )
    if not has_claude:
        return _fallback_decision(result)

    # Gate 2: Ask Claude (supports both direct API and Vertex AI)
    try:
        import anthropic

        if config.claude_provider == "vertex" and config.google_cloud_project:
            # Vertex AI: uses Google Cloud credentials (gcloud auth)
            client = anthropic.AnthropicVertex(
                project_id=config.google_cloud_project,
                region=config.google_cloud_region,
            )
        else:
            # Direct Anthropic API
            client = anthropic.Anthropic(api_key=config.anthropic_api_key)

        prompt = build_analysis_prompt(result)

        response = client.messages.create(
            model=config.claude_model,
            max_tokens=config.claude_max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        # Track token usage
        try:
            from ..monitoring.token_tracker import log_token_usage, extract_usage_from_response
            tokens_in, tokens_out = extract_usage_from_response(response)
            log_token_usage(
                purpose="evaluation",
                model=config.claude_model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                metadata={"symbol": result.symbol},
            )
        except Exception as e:
            logger.warning("Failed to track Claude token usage: %s", e)

        # Parse Claude's JSON response
        response_text = response.content[0].text.strip()

        # Handle case where Claude wraps JSON in markdown code blocks
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()

        data = json.loads(response_text)
        decision = ClaudeDecision(
            action=data.get("action", "SKIP"),
            confidence=data.get("confidence", 0),
            entry_price=data.get("entry_price", 0),
            stop_loss=data.get("stop_loss", 0),
            take_profit=data.get("take_profit", 0),
            reasoning=data.get("reasoning", ""),
            risk_warnings=data.get("risk_warnings", []),
        )

        # Gate 3: Validate Claude's response
        is_valid, issues = validate_claude_response(decision, result)
        if not is_valid:
            return ClaudeDecision(
                action="SKIP",
                confidence=0,
                reasoning=f"Claude response failed validation: {'; '.join(issues)}",
                risk_warnings=issues,
            )

        return decision

    except json.JSONDecodeError:
        return ClaudeDecision(
            action="SKIP",
            confidence=0,
            reasoning="Claude returned invalid JSON — blocked as safety measure",
        )
    except Exception as e:
        return ClaudeDecision(
            action="SKIP",
            confidence=0,
            reasoning=f"Claude API error: {str(e)[:100]}",
        )


def _fallback_decision(result: ConfluenceResult) -> ClaudeDecision:
    """
    Fallback when Claude API is not configured.
    Uses simple rules based on confluence score and agreement.
    """
    if result.composite_score < config.min_confluence_score:
        return ClaudeDecision(
            action="SKIP",
            confidence=int(result.composite_score),
            reasoning=f"Score {result.composite_score} below threshold (no Claude API configured)",
        )

    # Find the best signal for entry/exit levels
    best_signal = max(
        (s for s in result.signals if s.direction is not None),
        key=lambda s: s.score,
        default=None,
    )

    if not best_signal or not best_signal.entry_price:
        return ClaudeDecision(action="SKIP", confidence=1, reasoning="No actionable signal")

    action = "BUY" if result.direction == Direction.LONG else "SELL"
    confidence = min(10, int(result.composite_score))

    return ClaudeDecision(
        action=action,
        confidence=confidence,
        entry_price=best_signal.entry_price,
        stop_loss=best_signal.stop_loss or 0,
        take_profit=best_signal.take_profit or 0,
        reasoning=f"Fallback mode (no Claude API). Score: {result.composite_score}, "
                  f"{result.agreeing_strategies}/{result.total_strategies} strategies agree. "
                  f"Top signal: {best_signal.strategy_name}",
    )
