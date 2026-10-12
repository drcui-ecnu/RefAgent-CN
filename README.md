# RefAgent-CN

**Source-aware Chinese–English reference processing.**

Turn Chinese journal references into structured bibliographic metadata and English citations. RefAgent-CN combines reference parsing, verified knowledge-base lookup, and optional LLM generation, while keeping the source and review status of each field visible.

## Features

- **Reference parsing** — extract authors, title, journal, year, volume, issue, and pages.
- **Knowledge-base lookup** — reuse verified journal names and bilingual article titles.
- **Configurable models** — connect an OpenAI-compatible chat API or use cached responses offline.
- **Source-aware results** — distinguish verified, parsed, and generated fields, with human-review flags.
- **Citation rendering** — APA, MLA, Harvard, English GB/T-style, and bilingual GB/T-style output.
- **Bilingual interface** — English/Chinese Web UI with optional PDF text-layer input.

## Quick start

Requires Python 3.10 or later.

```bash
git clone https://github.com/drcui-ecnu/RefAgent-CN.git
cd RefAgent-CN
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e .
python examples/demo.py
```

The demo runs without an API key and uses synthetic KB records and a sample cached response:

```text
Input:
张三,李四.学术引用示例研究[J].示例图书馆学刊,2024,12(2):10-20.

APA output:
Zhang, S., & Li, S. (2024). An example study of academic references. Example Journal of Library Studies, 12(2), 10–20.
```

For your own references:

```bash
refagent-cn --reference "YOUR CHINESE REFERENCE" --journal-kb journal_kb.json --title-kb title_kb.json
```

Without a cached response or online generation, unavailable English fields remain empty.

## Web interface and PDF input

```bash
python -m pip install -e ".[web,pdf]"
streamlit run app.py
```

Paste a reference, load your KB files, and inspect field sources, review flags, and citation outputs. PDF input extracts embedded text; scanned documents require external OCR.

## Connect a model

Configure an OpenAI-compatible endpoint and model using environment variables. For example, in PowerShell:

```powershell
$env:REFAGENT_API_KEY="YOUR_API_KEY"
$env:REFAGENT_BASE_URL="https://your-provider.example/v1"
$env:REFAGENT_MODEL="your-chat-model"
refagent-cn --reference "YOUR CHINESE REFERENCE" --online --prompt prompts/shared_generation_v390.md
```

On macOS/Linux, use `export NAME="value"` for the same variables. Online mode makes one chat request per reference and may incur provider charges. Choose a model supporting chat-completions requests with system messages and JSON text responses. Provider-specific APIs may require an adapter. Keep credentials out of source control.

## How it works

Chinese reference + optional model response → parsing and verified KB lookup → source-aware field selection → citations and review flags.

Verified exact matches take priority over generated values. Generated metadata remains marked for review. Citation outputs should be checked before use.

## Knowledge bases and evaluation

Bring your own permitted Journal KB and bilingual Title KB JSON files. Full research KBs, the formal evaluation dataset, and model-response caches are not bundled; see [data schemas and resource availability](data/README.md).

Evaluate compatible Gold and prediction CSV files:

```bash
python evaluation/evaluate.py --gold evaluation.csv --predictions predictions.csv --output metrics.json
```

Metrics include structured-field accuracy, author identity, English-journal accuracy, title NEM, and chrF++. COMET is optional with `.[comet]` and a local checkpoint.

## Documentation

- [Reproducibility and experimental configuration](docs/reproducibility.md)
- [Data schemas](data/README.md)
- [Frozen resource checksums](docs/frozen_asset_manifest.json)
- [Dependency licenses](docs/third_party_notices.md)
- [Real-reference example](docs/usage_example.md)

Run tests with `python -m unittest discover -s tests -v`. Web/PDF tests require the corresponding optional dependencies.

## Citation

Associated manuscript: *Supporting Cross-Lingual Bibliographic Work with a Source-Aware Academic Agent: Evidence from Chinese Journal References*. Publication details will be added when available.

## License

Original code, documentation, and synthetic examples are MIT-licensed. Third-party data, dependencies, and model weights retain their own terms. PyMuPDF uses separate AGPL/commercial licensing.
