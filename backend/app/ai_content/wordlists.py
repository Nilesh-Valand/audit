"""
Curated phrase lists used by the rule-based analyzer.
These are editable — tune / extend them as you see false positives or negatives in real usage.
"""

# Words/phrases strongly associated with LLM-generated marketing/business prose
AI_ASSOCIATED_VOCAB = [
    "revolutionizing", "revolutionize", "pivotal role", "pivotal",
    "transformative", "leverage", "leveraging", "streamline", "streamlining",
    "seamless", "seamlessly", "robust", "cutting-edge", "state-of-the-art",
    "in today's fast-paced world", "in today's digital age", "unlock the potential",
    "unlocking", "landscape", "ever-evolving", "dynamic landscape",
    "paradigm shift", "holistic", "synergy", "synergies", "delve into", "delve",
    "navigate the complexities", "navigating", "underscore", "underscores",
    "underscoring", "testament to", "it is important to note", "it's worth noting",
    "furthermore", "moreover", "in conclusion", "in summary", "harness the power",
    "harnessing", "elevate", "elevating", "empower", "empowering", "empowers",
    "foster", "fostering", "fosters", "bespoke", "tailored solutions",
    "game-changer", "game changing", "innovative solutions", "meticulously",
    "myriad", "plethora", "top-notch", "unparalleled", "unprecedented", "tapestry",
]

# Generic / promotional filler common in AI-generated marketing copy
GENERIC_PROMOTIONAL = [
    "driving sustainable growth", "competitive advantage", "drive growth",
    "drive innovation", "unlock value", "maximize efficiency", "optimize performance",
    "enhance productivity", "improve customer experience", "customer experiences",
    "gain a competitive edge", "stay ahead of the curve", "stay competitive",
    "best-in-class", "world-class", "industry-leading", "next-generation",
    "future-proof", "end-to-end solution", "one-stop solution", "value-added",
    "mission-critical", "core competencies", "key takeaway", "actionable insights",
]

# Common LLM sentence-opener crutches — repeated use is a signal
SENTENCE_OPENER_CRUTCHES = [
    "furthermore", "moreover", "additionally", "in addition", "however",
    "therefore", "consequently", "notably", "importantly", "ultimately",
    "overall", "in conclusion", "in summary", "as a result",
]
