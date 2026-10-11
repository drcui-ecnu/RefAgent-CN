# RefAgent-CN

**A Source-Aware Academic Agent for Chinese–English Bibliographic Metadata Normalization**

RefAgent-CN parses Chinese references, combines verified metadata with optional controlled generation, and exposes field-level provenance and human-review routing. The paper-associated code is identified by the `paper-release` tag; its correspondence to the frozen experimental system is documented in [reproducibility](docs/reproducibility.md).

## Key features

- Chinese journal-reference parsing: authors, title, journal, year, volume, issue and pages.
- Exact verified title lookup and exact-priority journal lookup. The journal resolver also exposes SequenceMatcher candidates at 0.92; the evaluated hybrid does **not** adopt fuzzy candidates or implement independent Chinese-journal aliases.
- One optional DeepSeek request per reference; cached responses and missing-generation offline mode are supported.
- Field-level source, official/generated status, evidence identifiers and review flags.
- APA, MLA, Harvard, English GB/T-style and bilingual GB/T-style rendering. Outputs require bibliographic review; these are formatting implementations, not standards-compliance certification.
- An optional English/Chinese Streamlit interface and PDF text-layer ingestion; no built-in OCR.

## Installation

Python 3.10 or later:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e .
```

Optional interface: `python -m pip install -e ".[web]"`, then `streamlit run app.py`.
Optional PDF engine: `python -m pip install -e ".[pdf]"`. PyMuPDF has separate AGPL/commercial licensing; the original-code MIT license does not relicense it. An external `pdftotext` installation is an optional fallback.

## Quick start (no API key)

```bash
python examples/demo.py
python -m unittest discover -s tests -v
```

The author-created **fictitious** fixture uses:

```text
张三,李四.学术引用示例研究[J].示例图书馆学刊,2024,12(2):10-20.
```

Example APA rendering:

```text
Zhang, S., & Li, S. (2024). An example study of academic references. Example Journal of Library Studies, 12(2), 10–20.
```

The fixture's KB flags simulate verified records to test the interface contract; they are **not** evidence of a real journal or publication. The supplied response is cached illustrative input, not a formal model response. The returned `Generation_Mode`, provenance and `Review_Required` remain visible.

For references without a cache or API key, `refagent-cn --reference "YOUR REFERENCE"` still parses structured fields, but does not invent English titles or authors. Supply your own permitted KB JSON files with `--journal-kb` and `--title-kb`.

### Real-reference illustration

The following bibliographic example was run locally with the unrestricted frozen KB and an existing cached response (no new API request). Article metadata can be checked on the [official journal page](https://dik.whu.edu.cn/jwk3/tsqbzs/EN/10.13366/j.dik.2023.04.010).

```text
Input:
汤诚,刘晓霞,王春迎.场景理论视域下的“+城市公共阅读空间”营建[J].图书情报知识,2023,40(4):10-18,31.

APA output:
Tang, C., Liu, X., & Wang, C. (2023). Constructing integrated urban public reading space from the perspective of the theory of scenes. Documentation, Information & Knowledge, 40(4), 10–18,31.
```

The title came from an exact verified KB match; author names came from the cached response, with their generated provenance retained. This is a rendering illustration, not the masked formal-benchmark run or a claim of perfect APA compliance. The underlying full KB and response cache are not redistributed; the runnable public demo above is synthetic.

### Optional online generation

Set `DEEPSEEK_API_KEY` in your shell (do not commit it), then explicitly opt in:

```bash
refagent-cn --reference "YOUR REFERENCE" --online --prompt prompts/shared_generation_v390.md
```

This sends one API request and may incur costs. The formal request used `deepseek-chat`, temperature 0.2, max_tokens 512 and stream=false. The provider returned `deepseek-v4-flash` during the historical experiment; that backend is **not guaranteed** today. No top_p, seed or penalty defaults are guessed or added. Online calls were not executed while preparing this release.

## Knowledge bases and evaluation data

The full Journal KB (3,075), Title KB (3,372), other entity KBs, formal 300-record Gold data and model-response caches are **not bundled**, pending confirmation of third-party redistribution rights. Public availability of source pages is not a redistribution license. The algorithms, schema documentation and frozen checksums are provided; synthetic fixtures are not replacements for formal snapshots.

The formal held-out experiment used a **3,360-record masked Title KB**, not the unrestricted 3,372-record usage snapshot. See [reproducibility](docs/reproducibility.md), [resource schemas](data/README.md) and [frozen hashes](docs/frozen_asset_manifest.json).

## Evaluation and reproducibility

```bash
python evaluation/evaluate.py --gold YOUR_EVALUATION.csv --predictions YOUR_OUTPUT.csv --output metrics.json
```

This actually computes structured accuracy, final observable author identity and strict form, English-journal accuracy, title NEM, mean/corpus chrF++. COMET is optional and requires separately installed dependencies plus a local checkpoint:

```bash
python -m pip install -e ".[comet]"
python evaluation/evaluate.py --gold YOUR_EVALUATION.csv --predictions YOUR_OUTPUT.csv --comet-checkpoint YOUR_MODEL.ckpt
```

Full paper-result recomputation requires the corresponding private formal assets. No saved paper metric is used as a fixed evaluation output. Review-specific statistical analyses and human-rating data are intentionally not included.

## Citation

Associated manuscript (publication details not yet supplied): *Supporting Cross-Lingual Bibliographic Work with a Source-Aware Academic Agent: Evidence from Chinese Journal References*. Target journal: *The Journal of Academic Librarianship*. No DOI, volume or pages are asserted.

## License

Original code, documentation and explicitly synthetic fixtures: MIT. Third-party datasets, dependencies and model weights are excluded; see [third-party notices](docs/third_party_notices.md).

