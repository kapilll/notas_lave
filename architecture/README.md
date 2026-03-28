# Architecture (LikeC4)

Single source of truth for all architecture diagrams. Written in [LikeC4](https://likec4.dev/) DSL.

## Files

| File | Purpose |
|------|---------|
| `specs.c4` | Element types and styles (broker, strategy, storage, etc.) |
| `model.c4` | Complete system model — components and relationships |
| `views.c4` | 7 views at different zoom levels |

## Views

| View | Level | What it shows |
|------|-------|--------------|
| `index` | System Context | Trader, VM, external services |
| `vmOverview` | Container | Dashboard, Engine, Storage, Learning inside VM |
| `tradingFlowView` | Component | Lab Engine scan → signal → risk → broker flow |
| `strategiesView` | Detail | All 12 strategies by category |
| `storageView` | Component | EventStore + SQLAlchemy + JSON state |
| `learningView` | Component | Analyzer → Recommendations → Optimizer |
| `dataView` | Component | Market data sources and caching |

## Commands

```bash
# Preview live in browser (hot reload)
npx likec4 dev architecture/

# Export PNGs
npx likec4 export png -o docs/system/diagrams architecture/

# Export JSON (for programmatic use)
npx likec4 export json -o architecture.json architecture/
```

## VS Code

Install the [LikeC4 extension](https://marketplace.visualstudio.com/items?itemName=likec4.likec4-vscode) for live preview and autocomplete.

## Rules

- **Model is the source of truth.** Change `model.c4`, not the PNGs.
- **When you add/remove a component**, update `model.c4` and the relevant view in `views.c4`.
- **PNGs are gitignored** — they're generated artifacts. Regenerate with `npx likec4 export png`.
- **Keep Mermaid in ARCHITECTURE.md** as a lightweight fallback that renders on GitHub.
