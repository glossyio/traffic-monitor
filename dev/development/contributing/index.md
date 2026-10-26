# Contributing

Thank you for your interest in getting involved! We welcome all skill levels and abilities as contributions. Visit our [Traffic Monitor GitHub](https://github.com/glossyio/traffic-monitor) page to get involved.

Contributions can include any of the following plus more!

- 💡 [Feature requests](https://github.com/glossyio/traffic-monitor/issues/new?assignees=&labels=&projects=&template=feature_request.md&title=) and use case ideas
- 🐞 [Bug reports](https://github.com/glossyio/traffic-monitor/issues/new?assignees=&labels=&projects=&template=bug_report.md&title=)
- 👩‍💻 [Code contributions](https://github.com/glossyio/traffic-monitor/blob/main/CONTRIBUTING.md), see Contributing
- 👍 Comment on or thumbs-up [milestones](https://github.com/glossyio/traffic-monitor/milestones) or [issues](https://github.com/glossyio/traffic-monitor/issues)
- 💬 Questions, comments, and videos/images of your deployments on our [Traffic Monitor Zulip Chat](https://trafficmonitor.zulipchat.com/)!

We foster a safe and welcoming community, review [our Code of Conduct](https://github.com/glossyio/traffic-monitor?tab=coc-ov-file#readme).

## Use of AI tools

You may use AI coding assistants to help draft, review, or explain a contribution, but you remain its author: understand and test every change you submit. Never share images, video clips, or plate reads with an AI tool, and use placeholders instead of real passwords, keys, or tokens. The de-identified `tmdb.sqlite` database may be shared only with the device operator's explicit consent, and never if plate recognition was ever enabled, because it then holds plate numbers. See [Use of AI tools](https://github.com/glossyio/traffic-monitor/blob/dev/CONTRIBUTING.md#use-of-ai-tools) in CONTRIBUTING.md for the details and for how to label AI-assisted commits.

## Writing docs

These docs are Markdown files in the repo's [`docs/`](https://github.com/glossyio/traffic-monitor/tree/dev/docs) folder, built with [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/). Docs changes go in the same pull request as the code they describe, against `dev`.

- **Preview while you edit:** from the repo root, run `python3 -m venv ~/.venvs/tm-docs && ~/.venvs/tm-docs/bin/pip install --require-hashes -r docs-site/requirements.txt` once, then `~/.venvs/tm-docs/bin/mkdocs serve` and open <http://127.0.0.1:8000>.
- **Check before you push:** `mkdocs build --strict` fails on broken links, anchors, and images, and on pages missing from the nav. Pull requests run the same check.
- **New pages** go in the `nav:` list in `mkdocs.yml`, under the section for the reader's job (see below). A page outside the folders already listed under the `llmstxt` plugin also goes in that plugin's matching section, so AI tools can find it in `llms.txt`. Keep a page's file path when you move it in the nav; if the path must change, add the old path to the `moved` map in `docs-site/pages-root/404.html`.
- **Images** go in `docs/assets/images/`. Link them with Markdown, `![Alt text](../assets/images/name.png)`, so the build can check the path. Add a caption with `<figure markdown="span">` (see existing pages).
- **Callouts** use admonitions: `!!! info`, `!!! success`, `!!! warning`, or `!!! danger`, followed by the text indented four spaces.

Versions: pushes to `dev` publish to [`/dev/`](https://docs.trafficmonitor.ai/dev/), and each release tag (`vX.Y.Z`) publishes a frozen copy and becomes `/latest/`, the default version.

### Style

Aim for pages that are complete but quick to read: everything the reader needs, and nothing they don't. These rules apply to every docs change, whether a person or an AI tool drafted it.

- **One reader and one job per page.** Pages about installing, setup, configuration, the dashboards, and the data tell the person running a device what to do or what something means. Details for contributors go in the Development pages or in the README next to the code. [Diátaxis](https://diataxis.fr/) names the four jobs: tutorial, how-to guide, reference, and explanation. Use it to decide what belongs on the page you're editing, not to reorganize the site. The nav sections map to those jobs:

  | Section                                                                                                                                                                                                                                                                             | Job                                            | Reader                                  |
  | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- | --------------------------------------- |
  | Get started                                                                                                                                                                                                                                                                         | Explanation and orientation                    | Anyone new                              |
  | Build your own, Deploy, Add-ons                                                                                                                                                                                                                                                     | How-to guides, one task per page               | Someone building or installing a device |
  | Use the device                                                                                                                                                                                                                                                                      | How-to guides for the running device           | Someone operating a device              |
  | Reference                                                                                                                                                                                                                                                                           | Tables: every setting, flag, topic, and column | Someone looking a value up              |
  | Ideas and use cases, Help                                                                                                                                                                                                                                                           | Ideas, troubleshooting, and where to ask       | Someone curious or stuck                |
  | Development                                                                                                                                                                                                                                                                         | Contributors                                   | You                                     |
  | \* **Leave out what the reader won't act on,** such as Ansible variables and task names, Node-RED node names, and files they won't open. Give real values, such as the default install folder `/opt/traffic-monitor`, instead of variables.                                         |                                                |                                         |
  | \* **Revise in place.** Rewrite the text your change affects and delete what it makes obsolete, rather than adding a paragraph. Keep the docs edit in proportion to the change; a diff that removes more than it adds is fine.                                                      |                                                |                                         |
  | \* **Describe how things work, not how they changed.** Don't narrate changes ("now supports", "new in", "previously"). Each release has its own copy of the docs, and history belongs in commit messages and release notes.                                                         |                                                |                                         |
  | \* **Say each fact once,** and link to it from other pages. Link to config files and code in the repo instead of copying them into a page, because copies go stale. Link to the `main` branch, which tracks the latest release, so the link matches `/latest/` rather than `/dev/`. |                                                |                                         |
  | \* **Put the common case first.** Move edge cases and troubleshooting into a collapsed callout (`???` instead of `!!!`), a table, or the [FAQ](https://docs.trafficmonitor.ai/dev/help-and-faq/frequently-asked-questions/index.md).                                                |                                                |                                         |
  | \* **Use tables for reference data,** with one row per setting or database column and its type, default, and meaning.                                                                                                                                                               |                                                |                                         |
  | \* **Keep the language plain:** "you", present tense, active voice, short sentences, and no filler such as "simply", "just", or "note that". Save callouts for what the reader must not miss.                                                                                       |                                                |                                         |
  | \* **Check every value against the code,** including defaults, paths, ports, and names.                                                                                                                                                                                             |                                                |                                         |

For anything these rules don't cover, follow the [Google developer documentation style guide](https://developers.google.com/style).
