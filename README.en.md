# Maidundun AI Workbench

This collection comes from the content and retail operations of a neighborhood bakery. For store operations, use the offline inventory and voucher examples or the worked marketing cases. Choose a format, adapt the instructions to your own facts and images, and review the result using the method card. The detailed guides are in Chinese.

- [Design, documents and training deliveries](docs/design-delivery.md) · [Sales confirmation sheet](examples/sales-sheet/README.md) · [Training worksheet](examples/training-sheet/README.md)
- [Store operations and marketing](docs/store-operations.md) · [Stock pick list](examples/stock-pick/README.md) · [Voucher reconciliation](examples/voucher-review/README.md)
- [Six formats and sixteen methods](docs/content-paths.md)
- [Reference discovery and analysis](docs/research-radar.md)
- [Reusable shot-card instructions for an AI assistant](skills/reference-to-shot-cards/SKILL.md)

## Run the offline example

From the repository root, using Python 3.12 or later:

~~~shell
python examples/shot-cards/generate.py --input examples/shot-cards/demo.json --output shot-cards-demo.html
~~~

Open the generated HTML in your browser. Copy the JSON to plan another shoot and choose a new output file. The example uses only the Python standard library. Each guide distinguishes tested workflows from work still awaiting validation.

[中文首页](README.md) · [Attribution and licensing](ATTRIBUTION.md)
