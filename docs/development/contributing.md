# Contributing

Thank you for your interest in getting involved!  We welcome all skill levels and abilities as contributions. Visit our [Traffic Monitor GitHub](https://github.com/glossyio/traffic-monitor) page to get involved.

Contributions can include any of the following plus more!

* 💡 [Feature requests](https://github.com/glossyio/traffic-monitor/issues/new?assignees=\&labels=\&projects=\&template=feature_request.md\&title=) and use case ideas
* 🐞 [Bug reports](https://github.com/glossyio/traffic-monitor/issues/new?assignees=\&labels=\&projects=\&template=bug_report.md\&title=)
* 👩‍💻 [Code contributions](https://github.com/glossyio/traffic-monitor/blob/main/CONTRIBUTING.md), see Contributing
* 👍 Comment on or thumbs-up [milestones](https://github.com/glossyio/traffic-monitor/milestones) or [issues](https://github.com/glossyio/traffic-monitor/issues)
* 💬 Questions, comments, and videos/images of your deployments on our [Traffic Monitor Zulip Chat](https://trafficmonitor.zulipchat.com/)!

We foster a safe and welcoming community, review [our Code of Conduct](https://github.com/glossyio/traffic-monitor?tab=coc-ov-file#readme).

## Use of AI tools

You may use AI coding assistants to help draft, review, or explain a contribution, but you remain its author: understand and test every change you submit. Never share images, video clips, or plate reads with an AI tool, and use placeholders instead of real passwords, keys, or tokens. The de-identified `tmdb.sqlite` database may be shared only with the device operator's explicit consent, and never if plate recognition was ever enabled, because it then holds plate numbers. See [Use of AI tools](https://github.com/glossyio/traffic-monitor/blob/dev/CONTRIBUTING.md#use-of-ai-tools) in CONTRIBUTING.md for the details and for how to label AI-assisted commits.

## Writing docs

These docs are Markdown files in the repo's [`docs/`](https://github.com/glossyio/traffic-monitor/tree/dev/docs) folder, built with [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/). Docs changes go in the same pull request as the code they describe, against `dev`.

* **Preview while you edit:** from the repo root, run
  `python3 -m venv ~/.venvs/tm-docs && ~/.venvs/tm-docs/bin/pip install --require-hashes -r docs-site/requirements.txt`
  once, then `~/.venvs/tm-docs/bin/mkdocs serve` and open <http://127.0.0.1:8000>.
* **Check before you push:** `mkdocs build --strict` fails on broken links, anchors, and images, and on pages missing from the nav. Pull requests run the same check.
* **New pages** go in the `nav:` list in `mkdocs.yml`.
* **Images** go in `docs/assets/images/`. Link them with Markdown, `![Alt text](../assets/images/name.png)`, so the build can check the path. Add a caption with `<figure markdown="span">` (see existing pages).
* **Callouts** use admonitions: `!!! info`, `!!! success`, `!!! warning`, or `!!! danger`, followed by the text indented four spaces.

Versions: pushes to `dev` publish to [`/dev/`](https://docs.trafficmonitor.ai/dev/), and each release tag (`vX.Y.Z`) publishes a frozen copy and becomes `/latest/`, the default version.
