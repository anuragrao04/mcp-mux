# mcp-mux

Merge multiple instances of the same MCP server across environments into a single endpoint with a unified `env` parameter.

## Why?

Many MCP servers are environment specific. Organizations have multiple environments. For example, grafana prod and stage or coralogix prod and stage. They accept an auth token that's specific to a given environment. If an agent has to connect to multiple environments, it needs to connect to these different instances of the same MCP server - which duplicates tool definitions, descriptions, etc. in the context window. This tool solves it by merging all tools from different environment specific MCP servers and adding an `env` parameter to each tool. The AI Agent supplies the `env` parameter beside all other inputs for that tool and we route it to the right MCP server.
