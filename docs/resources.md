# Resources

Links worth keeping, harvested from
[`undefined-ui/second-brain-os`](https://github.com/undefined-ui/second-brain-os) (MIT, 811★)
and filtered to what is useful for an agent-maintained Markdown knowledge base.

Marker: **★** = directly usable (adopt / integrate / learn the API); **·** = inspiration.

## MCP

- **★** [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) — official reference servers (filesystem, memory).
- **★** [MarkusPfundstein/mcp-obsidian](https://github.com/MarkusPfundstein/mcp-obsidian) — Obsidian over the Local REST API plugin.
- **★** [coddingtonbear/obsidian-local-rest-api](https://github.com/coddingtonbear/obsidian-local-rest-api) — vault REST API; now ships its own `/mcp/` server.
- · [punkpeye/awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers) — community index of MCP servers.
- · [MCP spec update 2026-07-28](https://blog.modelcontextprotocol.io/posts/2026-07-28/) — MCP going stateless.

## Agent memory

- **★** [mem0ai/mem0](https://github.com/mem0ai/mem0) — reference **provider-string → factory** backend registry we mirror in `backends/`.
- **★** [getzep/graphiti](https://github.com/getzep/graphiti) — temporal KG for agents; edges carry validity windows, contradictions invalidate rather than overwrite.
- **★** [topoteretes/cognee](https://github.com/topoteretes/cognee) — graph + vector over many stores; `VectorDBInterface`/`GraphDBInterface` ABCs.
- · [doobidoo/mcp-memory-service](https://github.com/doobidoo/mcp-memory-service) — persistent memory over MCP with a knowledge graph.
- · [khoj-ai/khoj](https://github.com/khoj-ai/khoj) — self-hostable "AI second brain" with scheduled automations (closest product analog).
- · [reorproject/reor](https://github.com/reorproject/reor) — local-first note app that links notes as you write.

## GraphRAG / graph retrieval

- · [HKUDS/LightRAG](https://github.com/HKUDS/LightRAG) — dual-layer graph+vectors, cheap incremental updates.
- **★** [gusye1234/nano-graphrag](https://github.com/gusye1234/nano-graphrag) — GraphRAG in ~1,100 readable lines.
- · [microsoft/graphrag](https://github.com/microsoft/graphrag) — reference implementation; maintenance-mode.
- · [OSU-NLP-Group/HippoRAG](https://github.com/OSU-NLP-Group/HippoRAG) — personalised PageRank over a KG.
- · [DEEP-PolyU/Awesome-GraphRAG](https://github.com/DEEP-PolyU/Awesome-GraphRAG) — curated GraphRAG map.
- · [neuml/txtai](https://github.com/neuml/txtai) — embeddings DB + workflows, small enough to read.

## Papers

- · [GraphRAG — From Local to Global](https://arxiv.org/abs/2404.16130) — entity graph + community summaries.
- · [HippoRAG](https://arxiv.org/abs/2405.14831) — KG + personalised PageRank for multi-hop.
- · [HippoRAG 2 — From RAG to Memory](https://arxiv.org/abs/2502.14802) — graph memory beats plain vector RAG.
- · [LightRAG](https://arxiv.org/abs/2410.05779) — dual-level graph+vector design.
- **★** [Zep temporal knowledge graph](https://arxiv.org/abs/2501.13956) — why agent memory needs **time on the edges**; input for our freshness/supersession.
- · [When to Use Graphs in RAG](https://arxiv.org/abs/2506.05690) — where graph retrieval pays off vs overhead.
- **★** [Lost in the Middle](https://arxiv.org/abs/2307.03172) — long-context position degradation; basis for cited, small answers.

## Graph tooling

- **★** [NetworkX](https://networkx.org) — PageRank/betweenness/components over an exported edge list.
- **★** [InfraNodus Obsidian plugin](https://github.com/noduslabs/infranodus-obsidian-plugin) — centrality, clusters, **structural gaps** → blueprint for gap detection.
- · [Kuzu](https://kuzudb.com) — embedded graph DB, reads CSV directly.
- · [Gephi](https://gephi.org) — visual exploration of an exported GraphML.
- · [Knowledge Graphs for RAG (DeepLearning.AI)](https://www.deeplearning.ai/courses/knowledge-graphs-rag) · [Neo4j GraphAcademy](https://graphacademy.neo4j.com/knowledge-graph-rag/) — free courses.
- · [LLM Graph Transformer walkthrough](https://medium.com/data-science/building-knowledge-graphs-with-llm-graph-transformer-a91045c49b59).
- · [LazyGraphRAG](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/) — defer indexing cost to query time.

## Obsidian plugins

- · [Claudian](https://github.com/yishentu/claudian) — local agents inside the vault.
- · [Smart Connections](https://github.com/brianpetro/obsidian-smart-connections) — local embeddings surface related notes.
- **★** [Dataview](https://github.com/blacksmithgu/obsidian-dataview) — query frontmatter ("which pages have property P"); the shape-query we should expose.
- · [ExcaliBrain](https://github.com/zsviczian/excalibrain) — derives five relationship types from links/fields/tags.
- · [Graph Analysis](https://github.com/SkepticMystic/graph-analysis) · [Breadcrumbs](https://github.com/michaelpporter/breadcrumbs) — graph algorithms, typed links.
- · [Omnisearch](https://github.com/scambier/obsidian-omnisearch) · [Obsidian Linter](https://github.com/platers/obsidian-linter) · [find-unlinked-files](https://github.com/Vinzent03/find-unlinked-files).
- **★** [Obsidian Web Clipper](https://obsidian.md/clipper) — official capture into `raw/`.

## Capture / ingestion

- **★** [yt-dlp](https://github.com/yt-dlp/yt-dlp) · [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) — video → transcript.
- **★** [OCRmyPDF](https://github.com/ocrmypdf/OCRmyPDF) — text layer for scanned PDFs.
- · [memos](https://github.com/usememos/memos) — self-hosted markdown quick-capture inbox.
- · [ripgrep](https://github.com/BurntSushi/ripgrep) — fast enough that small vaults never need an index.

## Skills & pattern implementations

- **★** [anthropics/skills](https://github.com/anthropics/skills) — the official `SKILL.md` format reference.
- **★** [Graphify-Labs/graphify](https://github.com/Graphify-Labs/graphify) — folder → queryable graph; every edge labelled extracted/inferred.
- **★** [AgriciDaniel/claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian) — self-organizing vault, role presets.
- · [obra/superpowers](https://github.com/obra/superpowers) · [VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills) · [hesreallyhim/awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code).
- · [eugeniughelbur/obsidian-second-brain](https://github.com/eugeniughelbur/obsidian-second-brain) — 43-47 commands across Claude/Codex/Gemini, per-platform adapters.
- · [ballred/obsidian-claude-pkm](https://github.com/ballred/obsidian-claude-pkm) · [coleam00/second-brain-starter](https://github.com/coleam00/second-brain-starter) · [Astro-Han/karpathy-llm-wiki](https://github.com/Astro-Han/karpathy-llm-wiki) · [micuintus/llm-wiki](https://github.com/micuintus/llm-wiki).

## Harness / agent

- **★** [Claude Code docs](https://code.claude.com/docs/en/setup) · [hooks reference](https://code.claude.com/docs/en/hooks) · [plugin evals](https://code.claude.com/docs/en/plugin-evals) — `claude plugin eval`: six grader types + baseline delta; ready-made acceptance harness for our plugin.
- **★** [pi](https://github.com/earendil-works/pi) — deliberately minimal harness, ~⅓ the context per turn; read the source.
- · [smolagents](https://github.com/huggingface/smolagents) · [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview) · [humanlayer/12-factor-agents](https://github.com/humanlayer/12-factor-agents).

## Loop engineering

- · [Loop Engineering (O'Reilly)](https://www.oreilly.com/radar/loop-engineering/) · [Designing agentic loops](https://simonwillison.net/2025/Sep/30/designing-agentic-loops/).
- · [Stop Hand-Holding Your Coding Agent](https://arxiv.org/pdf/2607.00038) · [Less Context, Better Agents](https://arxiv.org/pdf/2606.10209).
- · [Ralph Wiggum as a software engineer](https://ghuntley.com/ralph/) · [Code review in the age of AI](https://addyosmani.com/blog/code-review-ai/).

## Eval

- **★** [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) — task selection, trajectory vs outcome grading, evals as CI.
- **★** [Your AI Product Needs Evals](https://hamel.dev/blog/posts/evals/) — the three levels + look-at-your-data.
- · [AI Evals FAQ](https://hamel.dev/blog/posts/evals-faq/) · [Who Validates the Validators?](https://arxiv.org/abs/2404.12272).
- · [promptfoo](https://www.promptfoo.dev/) · [Inspect (UK AISI)](https://inspect.aisi.org.uk/) · [terminal-bench](https://github.com/laude-institute/terminal-bench) · [Langfuse](https://langfuse.com/).

## Reading / pattern source

- **★** [Karpathy's llm-wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — the founding pattern; the wiki accumulates where RAG rediscovers.
- **★** [An organizational second brain (Meta Engineering)](https://engineering.fb.com/2026/09/02/ml-applications/organizational-second-brain-ai-learns-from-experts/) — 200+ frontmatter'd files as a dependency graph; strongest at-scale evidence.
- **★** [Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents) — direct input for our MCP tool surface.
- · [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) · [Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents).
- · [Managing context (Claude)](https://claude.com/blog/context-management) · [Manus: context engineering](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus) · [Context rot](https://www.trychroma.com/research/context-rot).
- · [How to build an agent](https://ampcode.com/notes/how-to-build-an-agent) · [The lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) · [Improved token efficiency (Cursor)](https://cursor.com/blog/improved-token-efficiency) · [Palantir AIP architecture](https://www.palantir.com/docs/foundry/architecture-center/aip-architecture).
- · [Andy Matuschak's notes](https://notes.andymatuschak.org) — evergreen notes in public.
