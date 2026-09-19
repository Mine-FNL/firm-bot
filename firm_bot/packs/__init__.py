"""firm-bot domain packs (v0.4+).

A "domain pack" is a self-contained bundle of vertical-specific tunings:

* an extractor / extractor overlay for vertical-specific document types
* a chunker overlay that respects vertical document structure
* a system-prompt overlay that primes the answer LLM for vertical work
* a sample corpus so users can ``firm-bot demo init --pack=<id>`` and
  see the pack in action immediately
* tests for the pack's components

Packs are **opt-in** — they never modify the base firm-bot pipeline. A
firm that does not load a pack sees exactly the same behaviour as
firm-bot shipped without this subpackage.

Available packs:

* :mod:`firm_bot.packs.litigation` — civil-litigation adversarial-document
  reading; adds transcript (page:line) and pleading (numbered-paragraph)
  extractors.
"""
