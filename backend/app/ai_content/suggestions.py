"""
Rule-based & LLM-powered suggestion generator.

The AI-likelihood score is computed 100% by rules in analyzer.py.
This module generates practical improvement suggestions for human writers:
- Rule-based smart suggestions are generated deterministically.
- Groq LLM suggestions are optionally generated if GROQ_API_KEY is available.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import List, Dict, Any, Optional


@dataclass
class Suggestion:
    detected_sentence: Optional[str]
    issue: str
    suggestion: str
    improved_direction: Optional[str]


def generate_rule_suggestions(
    sentence_scores: List[Dict[str, Any]],
    detected_patterns: List[Dict[str, Any]],
    top_n: int = 5,
) -> List[Dict[str, Any]]:
    """Deterministic, rule-based improvement suggestions."""
    suggestions: List[Dict[str, Any]] = []
    
    # Pick highest AI-likelihood sentences
    flagged = sorted(sentence_scores, key=lambda s: s.get("ai_likelihood", 0), reverse=True)[:top_n]
    flagged = [s for s in flagged if s.get("ai_likelihood", 0) >= 20]

    for item in flagged:
        text = item.get("text", "")
        score = item.get("ai_likelihood", 0)
        
        # Determine specific rule issue
        if any(w in text.lower() for w in ["revolutioniz", "leverage", "seamless", "pivotal", "transformative", "tapestry", "delve"]):
            suggestions.append({
                "detected_sentence": text,
                "issue": "Contains cliché AI marketing jargon.",
                "suggestion": "Replace buzzwords with direct, specific active verbs explaining the actual action.",
                "improved_direction": "Instead of 'leveraging seamless solutions', state the exact tool or method used.",
            })
        elif " and " in text and "," in text:
            suggestions.append({
                "detected_sentence": text,
                "issue": "Follows predictable triadic (rule-of-three) phrasing.",
                "suggestion": "Vary sentence rhythm by focusing on one key benefit or breaking into separate points.",
                "improved_direction": "Focus on the primary metric or outcome rather than listing three adjectives.",
            })
        elif score >= 50:
            suggestions.append({
                "detected_sentence": text,
                "issue": "Sentence structure is abstract with low concrete data.",
                "suggestion": "Add specific numbers, customer examples, or tangible facts to ground the statement.",
                "improved_direction": "Include actual percentages, names, or step-by-step details.",
            })
        else:
            suggestions.append({
                "detected_sentence": text,
                "issue": "Generic promotional phrasing.",
                "suggestion": "Simplify the phrase and focus on concrete user outcomes.",
                "improved_direction": "State directly what the reader will gain.",
            })

    # Add general pattern-level recommendations if sentence list is short
    if not suggestions:
        active = [p for p in detected_patterns if p.get("severity") in ("Medium", "High")]
        for p in active[:3]:
            suggestions.append({
                "detected_sentence": ", ".join(p.get("examples", [])[:3]) if p.get("examples") else None,
                "issue": f"High signal for {p.get('pattern')}.",
                "suggestion": f"Reduce repetitive patterns in {p.get('pattern').lower()}.",
                "improved_direction": "Incorporate real-world case studies and varied sentence lengths.",
            })

    return suggestions


def generate_llm_suggestions(
    sentence_scores: List[Dict[str, Any]],
    detected_patterns: List[Dict[str, Any]],
    top_n: int = 5,
) -> List[Dict[str, Any]]:
    """Optional Groq LLM suggestions (only executed if GROQ_API_KEY is configured)."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return generate_rule_suggestions(sentence_scores, detected_patterns, top_n)

    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

        flagged = sorted(sentence_scores, key=lambda s: s.get("ai_likelihood", 0), reverse=True)[:top_n]
        flagged = [s for s in flagged if s.get("ai_likelihood", 0) >= 20]
        if not flagged:
            return generate_rule_suggestions(sentence_scores, detected_patterns, top_n)

        active_patterns = [p.get("pattern") for p in detected_patterns if p.get("severity") in ("Medium", "High")]
        payload = [
            {
                "sentence": s.get("text"),
                "ai_likelihood": s.get("ai_likelihood"),
                "relevant_patterns": active_patterns,
            }
            for s in flagged
        ]

        system_prompt = """You are an assistant that rewrites AI-detector findings into short, practical improvement suggestions for a human writer.
For EACH flagged sentence, return a JSON object with:
- "detected_sentence": original sentence
- "issue": short sentence naming what's generic/robotic
- "suggestion": short actionable instruction to fix it
- "improved_direction": example of a concrete, natural rewrite

Return ONLY a JSON array of objects, no markdown preamble."""

        completion = client.chat.completions.create(
            model=model,
            temperature=0.4,
            max_tokens=1200,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps({"flagged_sentences": payload}, ensure_ascii=False)},
            ],
        )
        raw = completion.choices[0].message.content.strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(raw)
        return parsed
    except Exception:
        # Graceful fallback to rule-based suggestions on any LLM or network issue
        return generate_rule_suggestions(sentence_scores, detected_patterns, top_n)


def generate_suggestions(
    sentence_scores: List[Dict[str, Any]],
    detected_patterns: List[Dict[str, Any]],
    top_n: int = 5,
    use_llm: bool = False,
) -> List[Dict[str, Any]]:
    if use_llm and os.environ.get("GROQ_API_KEY"):
        return generate_llm_suggestions(sentence_scores, detected_patterns, top_n)
    return generate_rule_suggestions(sentence_scores, detected_patterns, top_n)
