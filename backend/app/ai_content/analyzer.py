"""
Rule-based AI-writing likelihood analyzer.

No LLM calls happen in this module. Every signal is computed
deterministically from the text itself, so results are reproducible,
fast, and fully explainable.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from statistics import mean, pstdev
from typing import List, Dict, Any, Tuple

from app.ai_content.wordlists import (
    AI_ASSOCIATED_VOCAB,
    GENERIC_PROMOTIONAL,
    SENTENCE_OPENER_CRUTCHES,
)

# Signal weights — must sum to 1.0.
WEIGHTS = {
    "ai_vocab": 0.18,
    "predictability": 0.12,
    "repetition": 0.12,
    "diversity": 0.13,
    "generic_promo": 0.13,
    "rule_of_three": 0.08,
    "sentence_variation": 0.09,
    "specificity": 0.15,
}

_nlp = None


def get_nlp():
    """Lazy-load spaCy model if available; return None if missing."""
    global _nlp
    if _nlp is False:
        return None
    if _nlp is None:
        try:
            import spacy
            _nlp = spacy.load("en_core_web_sm")
        except Exception:
            _nlp = False
            return None
    return _nlp


@dataclass
class DetectedPattern:
    pattern: str
    severity: str  # "Low" | "Medium" | "High"
    score: float   # 0-1 raw signal strength
    examples: List[str]


@dataclass
class SentenceScore:
    index: int
    text: str
    ai_likelihood: float  # 0-100


def _find_phrase_hits(text_lower: str, phrases: List[str]) -> List[str]:
    hits = []
    for phrase in phrases:
        if phrase in text_lower:
            hits.append(phrase)
    return hits


def _ngrams(words: List[str], n: int) -> List[str]:
    words_clean = [w.lower() for w in words]
    return [" ".join(words_clean[i : i + n]) for i in range(len(words_clean) - n + 1)]


def split_sentences(text: str) -> List[str]:
    """Split text into sentences using spaCy or regex fallback."""
    nlp = get_nlp()
    if nlp is not None:
        try:
            doc = nlp(text)
            return [sent.text.strip() for sent in doc.sents if sent.text.strip()]
        except Exception:
            pass
    # Regex fallback
    raw = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in raw if s.strip()]


def score_ai_vocab(text_lower: str, word_count: int) -> Tuple[float, List[str]]:
    hits = _find_phrase_hits(text_lower, AI_ASSOCIATED_VOCAB)
    if not hits or word_count < 10:
        return 0.0, []
    # Density: 4+ hits per 100 words -> max score
    density = (len(hits) / word_count) * 100
    score = min(density / 4.0, 1.0)
    return round(score, 3), hits


def score_generic_promo(text_lower: str, word_count: int) -> Tuple[float, List[str]]:
    hits = _find_phrase_hits(text_lower, GENERIC_PROMOTIONAL)
    if not hits or word_count < 10:
        return 0.0, []
    density = (len(hits) / word_count) * 100
    score = min(density / 3.0, 1.0)
    return round(score, 3), hits


def score_rule_of_three(text: str) -> Tuple[float, List[str]]:
    """Identifies 'X, Y, and Z' triadic structures common in AI writing."""
    pattern = r"\b([a-zA-Z\s]+),\s+([a-zA-Z\s]+),\s+and\s+([a-zA-Z\s]+)\b"
    matches = re.findall(pattern, text)
    examples = [f"{m[0].strip()}, {m[1].strip()}, and {m[2].strip()}" for m in matches[:4]]
    score = min(len(matches) / 2.0, 1.0)
    return score, examples


def score_repetition(words: List[str]) -> Tuple[float, List[str]]:
    if len(words) < 6:
        return 0.0, []
    bigrams = _ngrams(words, 2)
    trigrams = _ngrams(words, 3)
    combined = bigrams + trigrams
    counts = Counter(combined)
    repeated = [phrase for phrase, c in counts.items() if c > 1 and len(phrase.split()) >= 2]
    repeat_ratio = sum(c - 1 for c in counts.values() if c > 1) / max(len(combined), 1)
    score = min(repeat_ratio * 6.0, 1.0)
    return round(score, 3), repeated[:8]


def score_diversity(text: str) -> float:
    """Lower lexical diversity -> higher AI likelihood."""
    words = re.findall(r"[A-Za-z']+", text)
    if len(words) < 10:
        return 0.0
    try:
        from lexicalrichness import LexicalRichness
        lex = LexicalRichness(text)
        mtld = lex.mtld(threshold=0.72)
        normalized = 1.0 - min(max((mtld - 40) / 60.0, 0.0), 1.0)
        return round(normalized, 3)
    except Exception:
        ttr = len(set(w.lower() for w in words)) / len(words)
        return round(1.0 - min(ttr / 0.6, 1.0), 3)


def score_sentence_variation(sentences: List[str]) -> float:
    lengths = [len(s.split()) for s in sentences if s.strip()]
    if len(lengths) < 3:
        return 0.0
    m = mean(lengths)
    sd = pstdev(lengths)
    cv = sd / m if m > 0 else 0
    # Low coefficient of variation (uniform sentence lengths) -> high AI likelihood
    score = 1.0 - min(cv / 0.5, 1.0)
    return round(max(score, 0.0), 3)


def score_predictability(sentences: List[str]) -> Tuple[float, List[str]]:
    if len(sentences) < 2:
        return 0.0, []
    openers = [s.strip().split()[0].lower().strip(",.") for s in sentences if s.strip()]
    opener_counts = Counter(openers)
    repeated_openers = [w for w, c in opener_counts.items() if c > 1]

    crutch_hits = []
    for s in sentences:
        s_lower = s.lower()
        for crutch in SENTENCE_OPENER_CRUTCHES:
            if s_lower.strip().startswith(crutch):
                crutch_hits.append(crutch)

    signal = len(repeated_openers) + len(crutch_hits)
    score = min(signal / max(len(sentences) * 0.6, 1), 1.0)
    return round(score, 3), list(set(crutch_hits))


def score_specificity(text: str, sentences: List[str]) -> float:
    """Lower presence of numbers/named entities/proper nouns -> higher AI likelihood."""
    if not sentences:
        return 0.0
    nlp = get_nlp()
    if nlp is not None:
        try:
            doc = nlp(text)
            entity_count = len(doc.ents)
            number_count = len(re.findall(r"\b\d+([.,]\d+)?%?\b", doc.text))
            proper_noun_count = sum(1 for tok in doc if tok.pos_ == "PROPN")
            concrete_signals = entity_count + number_count + proper_noun_count
            density = concrete_signals / len(sentences)
            return round(1.0 - min(density / 1.0, 1.0), 3)
        except Exception:
            pass

    # Pure Regex Fallback
    number_count = len(re.findall(r"\b\d+([.,]\d+)?%?\b", text))
    proper_nouns = len(re.findall(r"\b[A-Z][a-z]+\b", text))
    concrete_signals = number_count + proper_nouns
    density = concrete_signals / max(len(sentences), 1)
    return round(1.0 - min(density / 1.5, 1.0), 3)


def severity_from_score(score: float) -> str:
    if score >= 0.6:
        return "High"
    if score >= 0.3:
        return "Medium"
    return "Low"


def analyze_text(text: str) -> Dict[str, Any]:
    text_clean = text.strip()
    if not text_clean:
        return {
            "overall_pct": 0.0,
            "confidence": "Low",
            "detected_patterns": [],
            "sentence_scores": [],
            "highlighted_phrases": [],
            "signals": {k: 0.0 for k in WEIGHTS},
        }

    sentences = split_sentences(text_clean)
    words = re.findall(r"[A-Za-z']+", text_clean)
    text_lower = text_clean.lower()
    word_count = len(words)

    ai_vocab_score, ai_vocab_hits = score_ai_vocab(text_lower, word_count)
    generic_score, generic_hits = score_generic_promo(text_lower, word_count)
    rule3_score, rule3_examples = score_rule_of_three(text_clean)
    repetition_score, repetition_hits = score_repetition(words)
    diversity_score = score_diversity(text_clean)
    variation_score = score_sentence_variation(sentences)
    predictability_score, predictability_hits = score_predictability(sentences)
    specificity_score = score_specificity(text_clean, sentences)

    signals = {
        "ai_vocab": ai_vocab_score,
        "predictability": predictability_score,
        "repetition": repetition_score,
        "diversity": diversity_score,
        "generic_promo": generic_score,
        "rule_of_three": rule3_score,
        "sentence_variation": variation_score,
        "specificity": specificity_score,
    }

    overall_raw = sum(signals[k] * WEIGHTS[k] for k in WEIGHTS)
    overall_pct = round(overall_raw * 100, 1)

    spread = pstdev(list(signals.values())) if len(signals) > 1 else 0
    distance_from_mid = abs(overall_raw - 0.5)
    if spread < 0.2 and distance_from_mid > 0.2:
        confidence = "High"
    elif spread < 0.3:
        confidence = "Medium"
    else:
        confidence = "Low"

    detected_patterns = [
        DetectedPattern(
            pattern="AI-associated vocabulary",
            severity=severity_from_score(ai_vocab_score),
            score=round(ai_vocab_score, 3),
            examples=ai_vocab_hits[:6],
        ),
        DetectedPattern(
            pattern="Generic / promotional language",
            severity=severity_from_score(generic_score),
            score=round(generic_score, 3),
            examples=generic_hits[:6],
        ),
        DetectedPattern(
            pattern="Rule-of-three structure",
            severity=severity_from_score(rule3_score),
            score=round(rule3_score, 3),
            examples=rule3_examples[:4],
        ),
        DetectedPattern(
            pattern="Repetition",
            severity=severity_from_score(repetition_score),
            score=round(repetition_score, 3),
            examples=repetition_hits,
        ),
        DetectedPattern(
            pattern="Low vocabulary diversity",
            severity=severity_from_score(diversity_score),
            score=round(diversity_score, 3),
            examples=[],
        ),
        DetectedPattern(
            pattern="Low sentence-length variation",
            severity=severity_from_score(variation_score),
            score=round(variation_score, 3),
            examples=[],
        ),
        DetectedPattern(
            pattern="Predictable sentence structure",
            severity=severity_from_score(predictability_score),
            score=round(predictability_score, 3),
            examples=predictability_hits[:6],
        ),
        DetectedPattern(
            pattern="Lack of specificity",
            severity=severity_from_score(specificity_score),
            score=round(specificity_score, 3),
            examples=[],
        ),
    ]

    sentence_scores = []
    nlp = get_nlp()
    for i, sent in enumerate(sentences):
        s_lower = sent.lower()
        s_words = re.findall(r"[A-Za-z']+", sent)
        s_word_count = max(len(s_words), 1)

        s_vocab_hits = _find_phrase_hits(s_lower, AI_ASSOCIATED_VOCAB)
        s_generic_hits = _find_phrase_hits(s_lower, GENERIC_PROMOTIONAL)
        s_vocab_density = min((len(s_vocab_hits) / s_word_count) * 100 / 4.0, 1.0)
        s_generic_density = min((len(s_generic_hits) / s_word_count) * 100 / 3.0, 1.0)

        if nlp is not None:
            try:
                sent_doc = nlp(sent)
                s_concrete = len(sent_doc.ents) + len(re.findall(r"\b\d+([.,]\d+)?%?\b", sent)) + \
                    sum(1 for tok in sent_doc if tok.pos_ == "PROPN")
            except Exception:
                s_concrete = len(re.findall(r"\b\d+([.,]\d+)?%?\b", sent)) + len(re.findall(r"\b[A-Z][a-z]+\b", sent))
        else:
            s_concrete = len(re.findall(r"\b\d+([.,]\d+)?%?\b", sent)) + len(re.findall(r"\b[A-Z][a-z]+\b", sent))

        s_specificity = 1.0 - min(s_concrete / 1.0, 1.0)

        blended = (
            0.40 * s_vocab_density +
            0.30 * s_generic_density +
            0.30 * s_specificity
        )
        sentence_scores.append(
            SentenceScore(index=i + 1, text=sent, ai_likelihood=round(blended * 100, 1))
        )

    highlighted_phrases = list(set(ai_vocab_hits + generic_hits + rule3_examples))

    return {
        "overall_pct": overall_pct,
        "confidence": confidence,
        "detected_patterns": [p.__dict__ for p in detected_patterns],
        "sentence_scores": [s.__dict__ for s in sentence_scores],
        "highlighted_phrases": highlighted_phrases,
        "signals": signals,
    }
