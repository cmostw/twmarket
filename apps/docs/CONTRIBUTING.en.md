# Documentation contribution guidelines

Update the relevant documentation whenever public interfaces, data semantics or workflows change. Choose the page's responsibility before writing.

## 1. Architecture and navigation

The entry page is the first-query tutorial. Other pages belong to How-to guides, Reference or Explanation. Index equities, emerging stocks, derivatives, company data and economic data by their actual query namespaces. Both languages share the same route structure: `.mdx` for Traditional Chinese and `.en.mdx` for English. Maintain ordering in `meta.json` and `meta.en.json`.

## 2. Documentation types

| Type | Purpose in twmarket | Boundary |
| --- | --- | --- |
| Tutorial | Learn through a first equity query | A defined starting point and observable outcome, without a parameter catalog |
| How-to guide | Complete batch queries, streaming, proxy configuration or DataFrame conversion | Solve a task without architecture discussions |
| Reference | Signatures, fields, units, date ranges and exceptions | Describe interfaces precisely without teaching steps |
| Explanation | Understand source differences, trading dates, contract mapping and data flow | Explain mechanisms without installation instructions |

## 3. Page templates

Provide a `title` and `description`. Tutorials contain a goal, prerequisites, steps and an outcome. How-to guides contain the task, prerequisites, a complete program and its result. Explanations introduce a question and explain relationships and tradeoffs. References use identifier headings, signatures and data contracts. Avoid link-only introductions and empty sections.

## 4. API documentation

Module summaries describe data responsibilities. Classes document purpose, state and lifecycle. Methods document actions, parameters, results and actual exceptions. Models document field meanings and source units. Distinguish lists, single models, async iterators and `BatchResult`, including empty results and individual failures.

API pages are generated from source. Edit docstrings rather than generated files:

```sh
cd apps/docs
npm run docs:generate
```

## 5. Docstrings

Follow PEP 257: use triple double quotes, start with a summary sentence and separate a multiline body with a blank line. Describe the action rather than repeat the signature. Document constructor arguments in `__init__`. Use Google-style `Args:`, `Returns:` and `Raises:` sections when needed; do not mix NumPy or Sphinx markup. Type annotations specify types; prose describes constraints and semantics.

Public bilingual docstrings place Chinese first, followed by a blank-line-separated `English:` section. Both summaries end with a period. Units, missing values, trading dates, contract identity and streaming state must also be documented in Chinese.

## 6. Examples

Runnable examples include imports and client lifecycle management. Async programs include `asyncio.run`. Streaming examples have an exit condition and close their iterator. Use string identifiers and explicit dates. Describe expected types or fields rather than invent fixed live prices or record counts. Link to extra installation before optional features.

## 7. Writing style

Use Traditional Chinese and separate English pages. Preserve API identifiers. Distinguish listed equities, OTC equities, emerging stocks, futures and options. Identify trading dates, source dates, retrieval times and reporting periods. `None` is missing data, not zero. Shares, lots, currency units, thousands and percentages are distinct. Describe tasks and data directly; omit promotion, self-assessment and editing history.

## 8. Formatting and notices

Use `python`, `sh` and `text` fences for Python, shell and output. Format paths, parameters and identifiers as inline code. Notes explain necessary conditions; warnings identify concrete risks of incorrect interpretation or loss; tips offer optional conveniences. Explain ordinary source differences in prose.

## 9. Cross-references

Use `/en/docs/...` for English and `/docs/...` for Chinese internal links, never `.mdx` targets. Link task pages to their APIs and necessary explanations. Link reference examples to guides or tutorials. Update links and old-route redirects when moving a page, preserving language counterparts.

## 10. Compatibility and deprecation

Installation requirements follow `pyproject.toml`. Record version or migration information only for released changes. Deprecation documentation provides the replacement and a confirmed removal version. Do not invent schedules.

## 11. Verification

Generate API pages, check types and build production output. Verify entry pages, language switching, search and internal links. Check Python example syntax and signatures first; network examples require separate source verification. Do not claim offline validation proves a live query succeeds. Add tests for observable contracts such as missing values, units, contract mapping and conversion, rather than each paragraph.

```sh
npm run types:check
npm run build
```

## 12. Maintenance

Update docstrings for public API changes, guides for workflow changes and references or explanations for semantic changes. Update both languages together and commit regenerated API pages. Comments explain code logic rather than version differences or writing history.
