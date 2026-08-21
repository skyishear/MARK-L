\# MARK L Prompt Rules



\## Repository

\- Read CLAUDE.md exactly once.

\- Read PROMPT\_RULES.md exactly once.

\- Repository is the only source of truth.



\## Token Efficiency

\- Minimize token usage.

\- Never scan unrelated folders.

\- Never reread unchanged files.

\- Read only required files.

\- Never summarize the repository.

\- Prefer implementation over commentary.



\## Output

\- Do not print complete contents of existing files.

\- Return only unified diffs (git-style patches) or concise change summaries.

\- Print complete contents only for newly created files if absolutely necessary.

\- Assume the attached ZIP will be used for merging.

\- Never duplicate unchanged code.

\- Rely on the attached ZIP instead of reproducing existing source files.



\## Scope

\- Preserve architecture.

\- No redesigns.

\- No rewrites.

\- No duplicate implementations.

\- Constructor injection everywhere.

\- Do not expand scope unless explicitly requested.



\## Testing

\- Run only affected tests.

\- Never run the full test suite unless strictly required.



\## Completion

\- Package the ZIP immediately after successful tests.

\- Stop immediately after packaging.

