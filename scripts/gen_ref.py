"""Generate the docs pages at build time.

Run by mkdocs-gen-files during ``mkdocs build``/``serve``. The home page is
sourced from the README and the API/CLI reference are rendered from the code, so
nothing hand-maintained or auto-generated is committed under ``docs/`` (where it
would otherwise show up as broken directives on GitHub).
"""

from pathlib import Path

import mkdocs_gen_files

with mkdocs_gen_files.open("index.md", "w") as fd:
    fd.write(Path("README.md").read_text(encoding="utf-8"))

_MEMBER_NESTING_CSS = """\
/* Indent members so they read as belonging to their parent — but only nested
   containers (a class's members), not the top-level module's own attributes
   and classes. A nested container is a .doc-children inside another. */
.doc-children .doc-children {
  margin-left: 1.2rem;
  padding-left: 1rem;
  border-left: 2px solid var(--md-default-fg-color--lightest);
}
.doc-children .doc-children > .doc-object {
  margin-top: 1rem;
}
"""

with mkdocs_gen_files.open("stylesheets/extra.css", "w") as fd:
    fd.write(_MEMBER_NESTING_CSS)

with mkdocs_gen_files.open("api.md", "w") as fd:
    fd.write("# API reference\n\n::: invisoutlet\n")

with mkdocs_gen_files.open("cli.md", "w") as fd:
    fd.write(
        "# CLI reference\n\n"
        "::: mkdocs-click\n"
        "    :module: invisoutlet.cli.app\n"
        "    :command: cli\n"
    )
