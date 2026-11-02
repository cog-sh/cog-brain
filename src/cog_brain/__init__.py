"""cog-brain — MCP server + incremental indexer for the SECOND_BRAIN Obsidian vault."""

__version__ = "0.1.0"


def __getattr__(name):
    if name == "Brain":
        from cog_brain.api import Brain
        return Brain
    raise AttributeError(name)
