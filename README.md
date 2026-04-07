# Architecture-Generation-Tool

Pipeline para gerar arquiteturas de microservicos a partir dos arquivos `input.txt` em:
- `dataspace/systems/student_projects`
- `dataspace/systems/open_source_projects`

Regras atuais:
- `student_projects`: gera arquitetura a partir do `input.txt` e compara com `DataMetrics.json`
- `open_source_projects`: gera arquitetura a partir do `input.txt` e compara com evidencias extraidas dos arquivos `.csv`

Comandos principais:
- `python -m server.core analyze --skip-llm`
- `python -m server.core analyze`
- `python -m server.core dashboard`
- `python -m client`
