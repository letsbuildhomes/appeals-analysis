# Changelog

## v0.0.1 (2026-10-19): the first release of the Vermont housing appeals data

- A dataset of every docket in the Vermont Environmental Division's published decisions, as of the court's
  October 19, 2026 listing: 1,736 dockets, 337 of them appeals of town decisions about new housing.
- For each appeal about new housing: the town's decision, who appealed and whether they had lawyers, the grounds
  argued, how the court heard and ended the case, how long it took, units and lots proposed and approved, stays
  and design changes the court imposed. Every answer drawn from a reasoning step carries a verified quote.
- Each release is frozen into its own files, with a data dictionary and its full provenance: the run, the
  pipeline, the models and the code.
- An MCP server at `https://data.letsbuildhomes.org/appeals/mcp`, open to anyone, so an AI assistant can
  describe, query and explain the data and read dockets with their quotes.
- A dashboard page (still a placeholder) and a read-only JSON API at the same site, both behind a shared password
  for now.
