# Spider, adapted

The queries in `queries.yaml` and the schemas in `schemas.yaml` come from the
development set of Spider:

> Tao Yu, Rui Zhang, Kai Yang, Michihiro Yasunaga, Dongxu Wang, Zifan Li, James Ma,
> Irene Li, Qingning Yao, Shanelle Roman, Zilin Zhang and Dragomir Radev. *Spider: A
> Large-Scale Human-Labeled Dataset for Complex and Cross-Domain Semantic Parsing and
> Text-to-SQL Task.* EMNLP 2018. <https://yale-lily.github.io/spider>

Spider is distributed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/),
and so is this directory, unlike the rest of forbql. The adaptation keeps only each
query's SQL, once per distinct query, and each database's tables and columns;
`build.py` makes both files from Spider's `dev.json` and `tables.json`.

forbql uses them to measure how often its firewall refuses queries people actually
write: see [`../REPORT.md`](../REPORT.md).
